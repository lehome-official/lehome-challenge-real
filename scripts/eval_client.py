#!/usr/bin/env python
"""
LeHome Challenge — Hardware Evaluation Client

Drives a real bi_so_follower robot by connecting to a policy server
(running in a Docker container) via gRPC, then executing the returned
action chunks on the physical arms.

Keyboard controls (during evaluation)
--------------------------------------
  →  or  d   Finish current episode early, move to next
  ←  or  a   Abort current episode and REDO it (scene wasn't ready, etc.)
  ESC         Stop the entire evaluation session immediately

Between episodes the script waits for ENTER before starting the next one.

Prerequisites
-------------
1. Complete environment setup  →  doc/01_environment.md
2. Configure serial ports and cameras  →  doc/02_robot_env.md
3. Open two terminals:

   Terminal A — start your policy Docker:
       docker run --rm -p 8080:8080 lehome-policy-<team>
       # wait for: "Policy server listening on 0.0.0.0:8080"

   Terminal B — run this script:
       source .venv/bin/activate
       source ./robot.env
       export TEAM=myteam
       bash scripts/start_eval_client.sh

Control loop (per episode)
--------------------------
    for each super-step:
        1. get_observation()            # read joints + cameras from robot
        2. SendObservations (gRPC)      # send to policy Docker
        3. GetActions       (gRPC)      # receive action chunk
        4. send_action() x chunk_size   # execute at 20 Hz
           (keyboard events checked between every action, ≤50 ms response)

Front-camera video is recorded at real-time speed: each captured frame is
duplicated actions_per_chunk times so the MP4 plays back without compression
artifacts or speed distortion.
"""

from __future__ import annotations

import argparse
import logging
import os
import pickle
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import grpc
import numpy as np
import torch

# ---------------------------------------------------------------------------
# LeRobot v0.5.1 imports
# ---------------------------------------------------------------------------
try:
    from lerobot.cameras import Cv2Backends
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.robots import make_robot_from_config
    from lerobot.robots.bi_so_follower import BiSOFollowerConfig
    from lerobot.robots.so_follower import SOFollowerConfig
except ImportError:
    print(
        "[eval_client] ERROR: LeRobot v0.5.1 not found.\n"
        "  Run:  source .venv/bin/activate\n"
        "  Then: uv pip install -e './third_party/lerobot[all]'\n"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# pynput — keyboard listener (part of lerobot[all] deps)
# ---------------------------------------------------------------------------
try:
    from pynput import keyboard as _kb
    _HAS_PYNPUT = True
except ImportError:
    _HAS_PYNPUT = False

# ---------------------------------------------------------------------------
# gRPC protocol — reuse the files shipped with docker/policy_server/
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "docker" / "policy_server"))

import services_pb2
import services_pb2_grpc
from protocol import RemotePolicyConfig, TimedAction, TimedObservation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("eval_client")

# ---------------------------------------------------------------------------
# Hardware spec — must match server.py / test_client.py exactly
# ---------------------------------------------------------------------------
MOTOR_NAMES = [
    "left_shoulder_pan.pos",  "left_shoulder_lift.pos", "left_elbow_flex.pos",
    "left_wrist_flex.pos",    "left_wrist_roll.pos",    "left_gripper.pos",
    "right_shoulder_pan.pos", "right_shoulder_lift.pos","right_elbow_flex.pos",
    "right_wrist_flex.pos",   "right_wrist_roll.pos",   "right_gripper.pos",
]
ACTION_DIM = len(MOTOR_NAMES)  # 12
CAMERA_NAMES = ["left_wrist", "right_wrist", "right_front"]

LEROBOT_FEATURES = {
    "observation.state": {
        "dtype": "float32", "shape": (ACTION_DIM,), "names": MOTOR_NAMES,
    },
    "observation.images.left_wrist":  {"dtype": "image", "shape": (480,  640,  3)},
    "observation.images.right_wrist": {"dtype": "image", "shape": (480,  640,  3)},
    "observation.images.right_front": {"dtype": "image", "shape": (720, 1280,  3)},
}

_TRANSFER_BEGIN = 1
_TRANSFER_END   = 3


# ---------------------------------------------------------------------------
# Keyboard event flags
# ---------------------------------------------------------------------------

@dataclass
class EvalEvents:
    """Shared state between the keyboard listener thread and the main loop."""
    exit_early:       bool = False   # → / d  : finish episode, go to next
    rerecord_episode: bool = False   # ← / a  : finish episode, redo same
    stop_session:     bool = False   # ESC    : stop everything

    def reset_episode(self):
        self.exit_early       = False
        self.rerecord_episode = False


def _init_keyboard_listener(events: EvalEvents):
    """Start a pynput listener thread; returns the listener (call .stop() to clean up)."""
    if not _HAS_PYNPUT:
        return None

    def on_press(key):
        if key in (_kb.Key.right, _kb.KeyCode.from_char("d")):
            if not events.exit_early:
                print("\n  [→] Finishing episode early ...")
            events.exit_early = True

        elif key in (_kb.Key.left, _kb.KeyCode.from_char("a")):
            if not events.rerecord_episode:
                print("\n  [←] Aborting episode — will redo ...")
            events.rerecord_episode = True
            events.exit_early       = True

        elif key == _kb.Key.esc:
            if not events.stop_session:
                print("\n  [ESC] Stopping evaluation session ...")
            events.stop_session = True
            events.exit_early   = True

    listener = _kb.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    return listener


# ---------------------------------------------------------------------------
# Robot construction
# ---------------------------------------------------------------------------

def _coerce_cam(val: str) -> int | str:
    """Return int if val is a numeric string (OpenCV index), else str (device path)."""
    return int(val) if val.lstrip("-").isdigit() else val


def _build_robot(args):
    """Instantiate a bi_so_follower robot from the CLI / env-var config."""
    left_arm_config = SOFollowerConfig(
        port=args.left_follower_port,
        cameras={
            "wrist": OpenCVCameraConfig(
                index_or_path=_coerce_cam(args.left_wrist_cam),
                width=args.left_wrist_width,
                height=args.left_wrist_height,
                fps=args.fps,
            ),
        },
    )
    right_arm_config = SOFollowerConfig(
        port=args.right_follower_port,
        cameras={
            "wrist": OpenCVCameraConfig(
                index_or_path=_coerce_cam(args.right_wrist_cam),
                width=args.right_wrist_width,
                height=args.right_wrist_height,
                fps=args.fps,
            ),
            "front": OpenCVCameraConfig(
                index_or_path=_coerce_cam(args.front_cam),
                width=args.front_width,
                height=args.front_height,
                fps=args.fps,
                backend=Cv2Backends.V4L2,
                fourcc="MJPG",
                warmup_s=5,
            ),
        },
    )
    cfg = BiSOFollowerConfig(
        id="bimanual_follower",
        left_arm_config=left_arm_config,
        right_arm_config=right_arm_config,
    )
    return make_robot_from_config(cfg)


def _validate_robot_features(robot):
    actual = list(robot.action_features)
    if actual != MOTOR_NAMES:
        raise RuntimeError(
            "LeRobot action feature order does not match the policy server protocol.\n"
            f"Expected: {MOTOR_NAMES}\n"
            f"Actual:   {actual}"
        )


# ---------------------------------------------------------------------------
# Observation conversion  LeRobot format → server format
# ---------------------------------------------------------------------------

def _lerobot_obs_to_server(lerobot_obs: dict, task: str) -> dict:
    """
    Convert a LeRobot v0.5.1 raw observation dict to the policy-server dict.

    LeRobot raw keys                       server keys
    ──────────────────────────────────────────────────────────────
    left_shoulder_pan.pos              →   left_shoulder_pan.pos
    left_wrist                         →   left_wrist   uint8 HWC
    right_wrist                        →   right_wrist  uint8 HWC
    right_front                        →   right_front  uint8 HWC
                                       →   task         str
    """
    missing = [key for key in [*MOTOR_NAMES, *CAMERA_NAMES] if key not in lerobot_obs]
    if missing:
        raise KeyError(
            "LeRobot observation is missing key(s) required by the policy server: "
            + ", ".join(missing)
        )

    server_obs: dict = {name: float(lerobot_obs[name]) for name in MOTOR_NAMES}
    server_obs["task"] = task

    for cam_name in CAMERA_NAMES:
        val = lerobot_obs[cam_name]
        if isinstance(val, torch.Tensor):
            img_tensor = val.detach().cpu()
            if img_tensor.ndim == 3 and img_tensor.shape[0] in (1, 3):
                img_tensor = img_tensor.permute(1, 2, 0)
            if img_tensor.dtype.is_floating_point:
                img_tensor = (img_tensor.clamp(0, 1) * 255).byte()
            img = img_tensor.numpy()
        else:
            img = np.asarray(val)
        server_obs[cam_name] = img.astype(np.uint8, copy=False)

    return server_obs


def _action_tensor_to_dict(action: torch.Tensor) -> dict[str, float]:
    if isinstance(action, torch.Tensor):
        values = action.detach().cpu().float().reshape(-1).tolist()
    else:
        values = np.asarray(action, dtype=np.float32).reshape(-1).tolist()

    if len(values) != ACTION_DIM:
        raise ValueError(f"Expected action with {ACTION_DIM} values, got {len(values)}.")

    return {name: float(values[i]) for i, name in enumerate(MOTOR_NAMES)}


# ---------------------------------------------------------------------------
# gRPC helpers
# ---------------------------------------------------------------------------

def _grpc_channel(server_addr: str) -> grpc.Channel:
    opts = [
        ("grpc.max_send_message_length",    64 * 1024 * 1024),
        ("grpc.max_receive_message_length", 64 * 1024 * 1024),
    ]
    return grpc.insecure_channel(server_addr, options=opts)


def _send_obs_stream(obs_bytes: bytes):
    mid = len(obs_bytes) // 2
    yield services_pb2.Observation(transfer_state=_TRANSFER_BEGIN, data=obs_bytes[:mid])
    yield services_pb2.Observation(transfer_state=_TRANSFER_END,   data=obs_bytes[mid:])


def _handshake(stub, server_addr: str, actions_per_chunk: int):
    stub.Ready(services_pb2.Empty(), timeout=10)
    log.info("Ready() — policy server connected at %s", server_addr)
    cfg = RemotePolicyConfig(
        policy_type="bi_so_follower",
        pretrained_name_or_path="",
        lerobot_features=LEROBOT_FEATURES,
        actions_per_chunk=actions_per_chunk,
        device="cpu",
    )
    stub.SendPolicyInstructions(
        services_pb2.PolicySetup(data=pickle.dumps(cfg)), timeout=15
    )
    log.info("SendPolicyInstructions() — config sent (actions_per_chunk=%d)", actions_per_chunk)


def _send_action_tensor(robot, action: torch.Tensor):
    """Convert the server's 12-D action tensor to LeRobot v0.5.1 action dict."""
    robot.send_action(_action_tensor_to_dict(action))


# ---------------------------------------------------------------------------
# Video recording
# ---------------------------------------------------------------------------

def _make_video_writer(output_dir: Path, team: str, task_slug: str,
                       width: int, height: int, fps: int):
    try:
        import cv2
    except ImportError:
        return None, None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{task_slug}_{team}_{ts}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    if not writer.isOpened():
        log.warning("VideoWriter failed to open — is opencv-python installed?")
        return None, None
    return writer, path


def _write_front_frame(writer, lerobot_obs: dict, n_duplicates: int):
    """
    Write the front-camera frame n_duplicates times so the MP4 plays at real-time speed.

    Because get_observation() is called once per action chunk (every 1 s at 20 fps),
    we duplicate each frame actions_per_chunk times to fill the 20-fps video timeline
    without speed distortion.
    """
    if writer is None or n_duplicates < 1:
        return
    try:
        import cv2
    except ImportError:
        return
    front = lerobot_obs.get("right_front")
    if front is None:
        return
    if isinstance(front, torch.Tensor):
        front = front.detach().cpu()
        if front.ndim == 3 and front.shape[0] in (1, 3):
            front = front.permute(1, 2, 0)
        if front.dtype.is_floating_point:
            front = (front.clamp(0, 1) * 255).byte()
        front = front.numpy()
    frame_bgr = cv2.cvtColor(np.asarray(front, dtype=np.uint8), cv2.COLOR_RGB2BGR)
    for _ in range(n_duplicates):
        writer.write(frame_bgr)


# ---------------------------------------------------------------------------
# One control super-step
# ---------------------------------------------------------------------------

def _run_step(
    stub,
    robot,
    task: str,
    timestep: int,
    actions_per_chunk: int,
    dt: float,
    events: EvalEvents,
) -> tuple[bool, dict | None]:
    """
    Capture one observation, get an action chunk from the server, and execute it.

    Keyboard events are checked between every individual action (≤ dt latency).
    Returns (success, lerobot_obs).  lerobot_obs is None on gRPC failure.
    """
    lerobot_obs = robot.get_observation()
    server_obs  = _lerobot_obs_to_server(lerobot_obs, task)

    timed_obs = TimedObservation(
        timestamp=time.time(),
        timestep=timestep,
        observation=server_obs,
        must_go=True,
    )
    obs_bytes = pickle.dumps(timed_obs)

    try:
        stub.SendObservations(_send_obs_stream(obs_bytes), timeout=10)
    except grpc.RpcError as e:
        log.error("SendObservations failed: %s — %s", e.code(), e.details())
        return False, None

    t_infer = time.perf_counter()
    try:
        response = stub.GetActions(services_pb2.Empty(), timeout=15)
    except grpc.RpcError as e:
        log.error("GetActions failed: %s — %s", e.code(), e.details())
        return False, None
    infer_ms = (time.perf_counter() - t_infer) * 1000

    if not response.data:
        log.warning("GetActions returned empty — server queue may be empty; robot holds position")
        return True, lerobot_obs

    actions: list[TimedAction] = pickle.loads(response.data)
    log.info(
        "step=%d  infer=%.0f ms  actions=%d  first=[%s]",
        timestep, infer_ms, len(actions),
        " ".join(f"{v:+.1f}" for v in actions[0].get_action().tolist()),
    )

    for timed_action in actions:
        if events.exit_early:
            break
        t0 = time.perf_counter()
        _send_action_tensor(robot, timed_action.get_action())
        elapsed = time.perf_counter() - t0
        time.sleep(max(0.0, dt - elapsed))

    return True, lerobot_obs


# ---------------------------------------------------------------------------
# Evaluation session
# ---------------------------------------------------------------------------

def _print_episode_banner(ep: int, n_episodes: int, task: str,
                          duration: int, server_addr: str, has_keys: bool):
    print(f"\n{'='*60}")
    print(f"  Episode {ep + 1}/{n_episodes}   task: {task}")
    print(f"  Max duration: {duration} s    server: {server_addr}")
    if has_keys:
        print(f"  Keys:  →/d finish    ←/a redo    ESC stop all")
    else:
        print(f"  (pynput unavailable — only Ctrl-C to stop)")
    print(f"{'='*60}")


def run_eval(args):
    # --- Keyboard listener ---
    events   = EvalEvents()
    listener = _init_keyboard_listener(events)
    if listener:
        log.info("Keyboard: →/d=next  ←/a=redo  ESC=stop")
    else:
        log.warning("pynput not available — keyboard controls disabled  (pip install pynput)")

    # --- Ctrl-C fallback ---
    def _sigint(_sig, _frame):
        print("\n[eval_client] Ctrl-C — stopping ...")
        events.stop_session = True
        events.exit_early   = True
    signal.signal(signal.SIGINT, _sigint)

    # --- Robot ---
    log.info("Connecting to robot (left=%s, right=%s) ...",
             args.left_follower_port, args.right_follower_port)
    robot = _build_robot(args)
    _validate_robot_features(robot)
    robot.connect()
    log.info("Robot connected.")

    # --- gRPC ---
    channel = _grpc_channel(args.server_addr)
    stub    = services_pb2_grpc.AsyncInferenceStub(channel)

    try:
        _handshake(stub, args.server_addr, args.actions_per_chunk)
    except grpc.RpcError as e:
        log.error("Handshake failed: %s — %s", e.code(), e.details())
        log.error("Is the policy Docker running?  docker run --rm -p 8080:8080 <image>")
        robot.disconnect()
        channel.close()
        if listener:
            listener.stop()
        sys.exit(1)

    dt        = 1.0 / args.fps
    task_slug = args.task.lower().replace(" ", "_")

    # --- Video (one continuous file for the entire session) ---
    video_dir = Path("Datasets") / "eval" / args.team / task_slug
    video_writer, video_path = _make_video_writer(
        video_dir, args.team, task_slug,
        width=args.front_width, height=args.front_height, fps=args.fps,
    )
    if video_path:
        log.info("Recording front camera → %s", video_path)
    else:
        log.info("Front-camera recording disabled (opencv-python not found or writer failed).")

    # ---------------------------------------------------------------------------
    # Episode loop
    # ---------------------------------------------------------------------------
    ep = 0
    try:
        while ep < args.n_episodes:
            if events.stop_session:
                break

            _print_episode_banner(
                ep, args.n_episodes, args.task,
                args.episode_duration, args.server_addr, listener is not None,
            )
            input("  Reset the scene, then press ENTER to start ...")

            if events.stop_session:
                break

            events.reset_episode()
            log.info("Episode %d/%d starting", ep + 1, args.n_episodes)
            ep_start = time.monotonic()
            timestep = 0

            # Control loop
            while not events.exit_early:
                elapsed = time.monotonic() - ep_start
                if elapsed >= args.episode_duration:
                    print(f"\n  [Time up — {args.episode_duration} s reached]")
                    break

                ok, lerobot_obs = _run_step(
                    stub, robot, args.task, timestep, args.actions_per_chunk, dt, events
                )
                if not ok:
                    log.error("Control step failed — aborting episode.")
                    break

                # Write each captured frame actions_per_chunk times so the MP4
                # plays at real-time speed (1 actual frame per second → 20 copies
                # fill the 20-fps video timeline correctly).
                _write_front_frame(video_writer, lerobot_obs, args.actions_per_chunk)
                timestep += args.actions_per_chunk

            elapsed = time.monotonic() - ep_start

            if events.rerecord_episode and not events.stop_session:
                print(f"\n  [Redo] Episode {ep + 1} aborted after {elapsed:.1f} s — will repeat.")
                events.reset_episode()
            else:
                log.info("Episode %d/%d done (%.1f s)", ep + 1, args.n_episodes, elapsed)
                ep += 1

    finally:
        if video_writer is not None:
            video_writer.release()
            if video_path:
                log.info("Video saved: %s", video_path)
        robot.disconnect()
        channel.close()
        if listener:
            listener.stop()
        log.info("Session ended — %d/%d episodes completed.", ep, args.n_episodes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def main():
    ap = argparse.ArgumentParser(
        description="LeHome hardware evaluation client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--server_addr",       default=_env("SERVER_ADDR",      "localhost:8080"))
    ap.add_argument("--team",              default=_env("TEAM",             "test_run"))
    ap.add_argument("--task",              default=_env("TASK",             "Fold the Garment"))
    ap.add_argument("--n_episodes",        type=int, default=int(_env("N_EPISODES",       "2")))
    ap.add_argument("--episode_duration",  type=int, default=int(_env("EPISODE_DURATION", "60")))
    ap.add_argument("--fps",               type=int, default=int(_env("FPS",              "20")))
    ap.add_argument("--actions_per_chunk", type=int, default=int(_env("ACTIONS_PER_CHUNK","20")))

    ap.add_argument("--left_follower_port",  default=_env("LEFT_FOLLOWER_PORT"))
    ap.add_argument("--right_follower_port", default=_env("RIGHT_FOLLOWER_PORT"))
    ap.add_argument("--left_wrist_cam",     default=_env("LEFT_WRIST_CAMERA_INDEX",  "0"))
    ap.add_argument("--right_wrist_cam",    default=_env("RIGHT_WRIST_CAMERA_INDEX", "1"))
    ap.add_argument("--front_cam",          default=_env("FRONT_CAMERA_INDEX",       "2"))
    ap.add_argument("--left_wrist_width",   type=int, default=int(_env("LEFT_WRIST_CAMERA_WIDTH",  "640")))
    ap.add_argument("--left_wrist_height",  type=int, default=int(_env("LEFT_WRIST_CAMERA_HEIGHT", "480")))
    ap.add_argument("--right_wrist_width",  type=int, default=int(_env("RIGHT_WRIST_CAMERA_WIDTH", "640")))
    ap.add_argument("--right_wrist_height", type=int, default=int(_env("RIGHT_WRIST_CAMERA_HEIGHT","480")))
    ap.add_argument("--front_width",        type=int, default=int(_env("FRONT_CAMERA_WIDTH",  "1280")))
    ap.add_argument("--front_height",       type=int, default=int(_env("FRONT_CAMERA_HEIGHT", "720")))

    args = ap.parse_args()

    missing = [k for k, v in {
        "LEFT_FOLLOWER_PORT  (--left_follower_port)":  args.left_follower_port,
        "RIGHT_FOLLOWER_PORT (--right_follower_port)": args.right_follower_port,
    }.items() if not v]
    if missing:
        ap.error(
            "Missing robot serial port(s):\n"
            + "\n".join(f"  {m}" for m in missing)
            + "\n\nRun `source ./robot.env` first, or pass the flags explicitly."
        )

    run_eval(args)


if __name__ == "__main__":
    main()
