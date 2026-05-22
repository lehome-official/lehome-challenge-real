#!/usr/bin/env python
"""
Mock policy server — lets you verify robot hardware wiring without a real model.

Modes
-----
  (default)  Hold-position: returns the current joint state unchanged.
             Arms will not move.  Use this to confirm the gRPC pipeline works
             before connecting a real policy.

  --demo     Sine-wave: adds a small oscillation to each joint.
             Arms will move visibly.  Use this to confirm the robot responds
             correctly to commands.

Usage
-----
    # Terminal A — start mock server:
    source .venv/bin/activate
    python scripts/mock_policy_server.py --port=8080

    # Terminal A — sine-wave demo (arms move):
    python scripts/mock_policy_server.py --port=8080 --demo --amplitude=5 --period=6

    # Terminal B — start the real hardware eval client:
    bash scripts/start_eval_client.sh

Safety
------
Keep --amplitude small (≤ 10 degrees) and confirm the arms have clearance
before running --demo.  Press Ctrl-C in Terminal A to stop the server
immediately; the arms will hold their last commanded position.
"""

from __future__ import annotations

import argparse
import io
import logging
import math
import os
import pickle
import sys
import threading
import time
from concurrent import futures
from pathlib import Path
from queue import Empty, Queue

import grpc
import torch

# gRPC protocol — reuse docker/policy_server/ files (single source of truth)
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "docker" / "policy_server"))

import services_pb2
import services_pb2_grpc
from protocol import RemotePolicyConfig, TimedAction, TimedObservation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mock_server")

MOTOR_NAMES = [
    "left_shoulder_pan.pos",  "left_shoulder_lift.pos", "left_elbow_flex.pos",
    "left_wrist_flex.pos",    "left_wrist_roll.pos",    "left_gripper.pos",
    "right_shoulder_pan.pos", "right_shoulder_lift.pos","right_elbow_flex.pos",
    "right_wrist_flex.pos",   "right_wrist_roll.pos",   "right_gripper.pos",
]
ACTION_DIM = len(MOTOR_NAMES)

_TRANSFER_BEGIN  = 1
_TRANSFER_MIDDLE = 2
_TRANSFER_END    = 3


def _recv_chunks(iterator, shutdown: threading.Event) -> bytes | None:
    buf = io.BytesIO()
    for item in iterator:
        if shutdown.is_set():
            return None
        if item.transfer_state == _TRANSFER_BEGIN:
            buf.seek(0); buf.truncate(0); buf.write(item.data)
        elif item.transfer_state == _TRANSFER_MIDDLE:
            buf.write(item.data)
        elif item.transfer_state == _TRANSFER_END:
            buf.write(item.data)
            return buf.getvalue()
    return None


class MockPolicyServer(services_pb2_grpc.AsyncInferenceServicer):

    def __init__(self, fps: int, chunk: int, demo: bool, amplitude: float, period: float):
        self.dt        = 1.0 / fps
        self.chunk     = chunk
        self.demo      = demo
        self.amplitude = amplitude
        self.period    = period

        self._obs_queue = Queue(maxsize=1)
        self._shutdown  = threading.Event()
        self._step      = 0

        mode = f"sine-wave (amplitude={amplitude} deg, period={period} s)" if demo else "hold-position"
        log.info("MockPolicyServer ready  mode=%s  chunk=%d  fps=%d", mode, chunk, fps)

    def Ready(self, _request, _context):
        log.info("Ready() — client connected")
        self._shutdown.clear()
        return services_pb2.Empty()

    def SendPolicyInstructions(self, request, _context):
        cfg: RemotePolicyConfig = pickle.loads(request.data)
        self.chunk = cfg.actions_per_chunk
        log.info("SendPolicyInstructions: chunk=%d", self.chunk)
        return services_pb2.Empty()

    def SendObservations(self, request_iterator, _context):
        raw = _recv_chunks(request_iterator, self._shutdown)
        if raw is None:
            return services_pb2.Empty()
        timed_obs: TimedObservation = pickle.loads(raw)
        obs = timed_obs.get_observation()
        state = [obs.get(k, 0.0) for k in MOTOR_NAMES]
        log.info(
            "Received obs #%d  state[0:3]=[%+.2f %+.2f %+.2f]",
            timed_obs.get_timestep(), *state[:3],
        )
        if self._obs_queue.full():
            self._obs_queue.get_nowait()
        self._obs_queue.put(timed_obs)
        return services_pb2.Empty()

    def GetActions(self, _request, _context):
        try:
            timed_obs: TimedObservation = self._obs_queue.get(timeout=5)
        except Empty:
            log.warning("GetActions: queue empty — returning empty response")
            return services_pb2.Actions(data=b"")

        t0  = timed_obs.get_timestamp()
        ts0 = timed_obs.get_timestep()
        obs = timed_obs.get_observation()

        state = torch.tensor(
            [obs.get(k, 0.0) for k in MOTOR_NAMES], dtype=torch.float32
        )

        chunk: list[TimedAction] = []
        for i in range(self.chunk):
            t = t0 + i * self.dt
            if self.demo:
                phase = 2 * math.pi * t / self.period
                delta = torch.tensor(
                    [self.amplitude * math.sin(phase + j * math.pi / ACTION_DIM)
                     for j in range(ACTION_DIM)],
                    dtype=torch.float32,
                )
                action = state + delta
            else:
                action = state.clone()

            chunk.append(TimedAction(timestamp=t, timestep=ts0 + i, action=action))

        self._step += self.chunk
        vals = " ".join(f"{v:+.1f}" for v in chunk[0].get_action().tolist())
        log.info("GetActions #%d → %d actions  [%s]", ts0, len(chunk), vals)
        return services_pb2.Actions(data=pickle.dumps(chunk))


def serve(args):
    server_instance = MockPolicyServer(
        fps=args.fps, chunk=args.chunk,
        demo=args.demo, amplitude=args.amplitude, period=args.period,
    )
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    services_pb2_grpc.add_AsyncInferenceServicer_to_server(server_instance, grpc_server)
    grpc_server.add_insecure_port(f"0.0.0.0:{args.port}")
    grpc_server.start()
    log.info("Mock policy server listening on 0.0.0.0:%d", args.port)
    log.info("Press Ctrl-C to stop")
    try:
        grpc_server.wait_for_termination()
    except KeyboardInterrupt:
        server_instance._shutdown.set()
        grpc_server.stop(grace=1)


def main():
    ap = argparse.ArgumentParser(description="Mock gRPC policy server for hardware testing")
    ap.add_argument("--port",      type=int,   default=8080)
    ap.add_argument("--fps",       type=int,   default=20)
    ap.add_argument("--chunk",     type=int,   default=20)
    ap.add_argument("--demo",      action="store_true",
                    help="Enable sine-wave motion (arms will move)")
    ap.add_argument("--amplitude", type=float, default=5.0,
                    help="Sine-wave amplitude in degrees (default: 5)")
    ap.add_argument("--period",    type=float, default=6.0,
                    help="Sine-wave period in seconds (default: 6)")
    serve(ap.parse_args())


if __name__ == "__main__":
    main()
