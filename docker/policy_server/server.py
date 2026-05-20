"""
Policy server template — replace the inference logic with your model.

This file implements the AsyncInference gRPC service.  The robot client
connects here, sends observations, and expects action chunks in return.

How to adapt
------------
1. Load your model in PolicyServer.__init__.
2. Replace _predict() with your model's forward pass.
3. Keep the gRPC handler signatures and return types unchanged.

Run locally (outside Docker)
----------------------------
    python server.py --host=0.0.0.0 --port=8080

Inside Docker (see entrypoint.sh), SERVER_HOST / SERVER_PORT are passed
as environment variables.
"""

from __future__ import annotations

# Ensure protocol and services_pb2* are importable whether running inside Docker
# (/app is the working dir) or directly from the project root.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Pickle compatibility — must come BEFORE any pickle.loads call.
#
# The robot client serializes objects under lerobot.async_inference.helpers.*
# This Docker has no lerobot package, so we register our local protocol
# classes under those module paths so pickle can deserialize them correctly.
# ---------------------------------------------------------------------------
import types as _types
import protocol as _p

def _register_pickle_compat():
    for pkg in ("lerobot", "lerobot.async_inference"):
        if pkg not in _sys.modules:
            _sys.modules[pkg] = _types.ModuleType(pkg)
    mod = _types.ModuleType("lerobot.async_inference.helpers")
    for name in ("TimedData", "TimedAction", "TimedObservation", "RemotePolicyConfig"):
        cls = getattr(_p, name)
        cls.__module__ = "lerobot.async_inference.helpers"
        setattr(mod, name, cls)
    _sys.modules["lerobot.async_inference.helpers"] = mod

_register_pickle_compat()
# ---------------------------------------------------------------------------

import argparse
import io
import logging
import os
import pickle
import threading
import time
from concurrent import futures
from queue import Empty, Queue

import grpc
import numpy as np
import torch

import services_pb2
import services_pb2_grpc
from protocol import RemotePolicyConfig, TimedAction, TimedObservation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("policy_server")

# Motor order must match the robot client exactly.
MOTOR_NAMES = [
    "left_shoulder_pan.pos",  "left_shoulder_lift.pos", "left_elbow_flex.pos",
    "left_wrist_flex.pos",    "left_wrist_roll.pos",    "left_gripper.pos",
    "right_shoulder_pan.pos", "right_shoulder_lift.pos","right_elbow_flex.pos",
    "right_wrist_flex.pos",   "right_wrist_roll.pos",   "right_gripper.pos",
]
ACTION_DIM = len(MOTOR_NAMES)  # 12

_TRANSFER_BEGIN  = 1
_TRANSFER_MIDDLE = 2
_TRANSFER_END    = 3


def _recv_chunks(iterator, shutdown: threading.Event) -> bytes | None:
    """Reassemble a chunked gRPC byte stream into a single bytes object."""
    buf = io.BytesIO()
    for item in iterator:
        if shutdown.is_set():
            return None
        state = item.transfer_state
        if state == _TRANSFER_BEGIN:
            buf.seek(0)
            buf.truncate(0)
            buf.write(item.data)
        elif state == _TRANSFER_MIDDLE:
            buf.write(item.data)
        elif state == _TRANSFER_END:
            buf.write(item.data)
            return buf.getvalue()
    return None


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host",  default=os.environ.get("SERVER_HOST", "0.0.0.0"))
    ap.add_argument("--port",  type=int, default=int(os.environ.get("SERVER_PORT", "8080")))
    ap.add_argument("--fps",   type=int, default=int(os.environ.get("SERVER_FPS",  "20")))
    ap.add_argument("--chunk", type=int, default=int(os.environ.get("SERVER_CHUNK", "20")))
    return ap.parse_args()


# ---------------------------------------------------------------------------
# Policy server
# ---------------------------------------------------------------------------

class PolicyServer(services_pb2_grpc.AsyncInferenceServicer):
    """
    Implements the AsyncInference gRPC service.

    The observation queue (maxsize=1) keeps only the latest frame so that
    inference always runs on fresh data and never falls behind.
    """

    def __init__(self, fps: int, chunk: int):
        self.dt    = 1.0 / fps
        self.chunk = chunk

        self._obs_queue            = Queue(maxsize=1)
        self._shutdown             = threading.Event()
        self._actions_per_chunk    = chunk
        self._step                 = 0

        # ----------------------------------------------------------------
        # [CONTESTANT] Load your model here.
        # Example:
        #   self.model = YourModel.from_pretrained("/app/checkpoints")
        #   self.model.eval()
        # ----------------------------------------------------------------
        self.model = None
        log.info("PolicyServer ready (action_dim=%d, chunk=%d, fps=%d)", ACTION_DIM, chunk, fps)

    # ------------------------------------------------------------------
    # gRPC handlers — do not change signatures
    # ------------------------------------------------------------------

    def Ready(self, _request, _context):
        """Handshake: called once when the robot client connects."""
        log.info("Ready() — robot client connected")
        self._shutdown.clear()
        return services_pb2.Empty()

    def SendPolicyInstructions(self, request, _context):
        """Called after Ready(). Contains team metadata; model is pre-loaded."""
        specs: RemotePolicyConfig = pickle.loads(request.data)
        self._actions_per_chunk = specs.actions_per_chunk
        log.info(
            "SendPolicyInstructions: policy_type=%s  path=%s  chunk=%d",
            specs.policy_type, specs.pretrained_name_or_path, specs.actions_per_chunk,
        )
        return services_pb2.Empty()

    def SendObservations(self, request_iterator, _context):
        """Receive a stream of bytes forming one pickled TimedObservation."""
        raw = _recv_chunks(request_iterator, self._shutdown)
        if raw is None:
            return services_pb2.Empty()

        timed_obs: TimedObservation = pickle.loads(raw)
        obs = timed_obs.get_observation()

        state = [obs.get(k, 0.0) for k in MOTOR_NAMES]
        log.info(
            "Received obs #%d  state[0:3]=[%+.2f %+.2f %+.2f]  cameras=%s",
            timed_obs.get_timestep(),
            *state[:3],
            [k for k, v in obs.items() if isinstance(v, np.ndarray)],
        )

        if self._obs_queue.full():
            self._obs_queue.get_nowait()
        self._obs_queue.put(timed_obs)
        return services_pb2.Empty()

    def GetActions(self, _request, _context):
        """Run inference on the latest observation and return an action chunk."""
        try:
            timed_obs: TimedObservation = self._obs_queue.get(timeout=5)
        except Empty:
            log.warning("GetActions: observation queue empty — returning empty response")
            return services_pb2.Actions(data=b"")

        t0  = timed_obs.get_timestamp()
        ts0 = timed_obs.get_timestep()
        obs = timed_obs.get_observation()

        # ----------------------------------------------------------------
        # [CONTESTANT] Replace this with your model's forward pass.
        # _predict() must return a list of torch.Tensor of shape (ACTION_DIM,).
        # ----------------------------------------------------------------
        action_chunk = self._predict(obs)

        chunk = [
            TimedAction(
                timestamp=t0 + i * self.dt,
                timestep=ts0 + i,
                action=action_chunk[i],
            )
            for i in range(len(action_chunk))
        ]
        self._step += len(chunk)

        vals = "  ".join(f"{v:+.2f}" for v in chunk[0].get_action().tolist())
        log.info("GetActions #%d → %d actions  [%s]", ts0, len(chunk), vals)
        return services_pb2.Actions(data=pickle.dumps(chunk))

    # ------------------------------------------------------------------
    # [CONTESTANT] Replace this with your model's inference logic
    # ------------------------------------------------------------------

    def _predict(self, obs: dict) -> list[torch.Tensor]:
        """
        Given a raw observation dict, return a list of `self.chunk` action tensors,
        each of shape (ACTION_DIM,) = (12,).

        This default echoes the current joint state (hold position).
        Replace with your model's forward pass.

        Example:
            images = preprocess_images(obs)
            state  = torch.tensor([obs[k] for k in MOTOR_NAMES])
            with torch.no_grad():
                actions = self.model(images, state)  # shape (chunk, 12)
            return list(actions)
        """
        state = torch.tensor([obs.get(k, 0.0) for k in MOTOR_NAMES], dtype=torch.float32)
        return [state.clone() for _ in range(self.chunk)]


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def serve(args):
    server_instance = PolicyServer(fps=args.fps, chunk=args.chunk)
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    services_pb2_grpc.add_AsyncInferenceServicer_to_server(server_instance, grpc_server)
    grpc_server.add_insecure_port(f"{args.host}:{args.port}")
    grpc_server.start()
    log.info("Policy server listening on %s:%d", args.host, args.port)
    log.info("Press Ctrl-C to stop")
    try:
        grpc_server.wait_for_termination()
    except KeyboardInterrupt:
        server_instance._shutdown.set()
        grpc_server.stop(grace=1)


if __name__ == "__main__":
    serve(_parse_args())
