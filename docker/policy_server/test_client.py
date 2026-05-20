#!/usr/bin/env python
"""
Standalone smoke test for the LeHome Challenge policy server.

No lerobot install required — only grpcio, numpy, and torch (same
dependencies as requirements.txt inside the Docker image).

Stages
------
  --stage 1   Handshake only (Ready + SendPolicyInstructions).
              Verifies the gRPC transport works and the server starts up.

  --stage 2   Full obs→action loop (default).
              Sends N fake observations matching the bi_so_follower format
              and checks that each action chunk has the correct shape and dtype.

Usage
-----
    # Against your running Docker (most common):
    python test_client.py --server_addr=localhost:8080

    # Stage 1 only (faster handshake check):
    python test_client.py --server_addr=localhost:8080 --stage=1

    # More round-trips:
    python test_client.py --server_addr=localhost:8080 --n_steps=10
"""

from __future__ import annotations

import argparse
import io
import os
import pickle
import sys
import time

import grpc
import numpy as np
import torch

# Make the sibling protocol / services files importable regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import services_pb2
import services_pb2_grpc
from protocol import RemotePolicyConfig, TimedAction, TimedObservation

# ---------------------------------------------------------------------------
# Robot spec — must match the server's MOTOR_NAMES exactly
# ---------------------------------------------------------------------------

MOTOR_NAMES = [
    "left_shoulder_pan.pos",  "left_shoulder_lift.pos", "left_elbow_flex.pos",
    "left_wrist_flex.pos",    "left_wrist_roll.pos",    "left_gripper.pos",
    "right_shoulder_pan.pos", "right_shoulder_lift.pos","right_elbow_flex.pos",
    "right_wrist_flex.pos",   "right_wrist_roll.pos",   "right_gripper.pos",
]
ACTION_DIM = len(MOTOR_NAMES)  # 12

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
# Helpers
# ---------------------------------------------------------------------------

def _grpc_channel(server_addr: str) -> grpc.Channel:
    options = [
        ("grpc.max_send_message_length",    64 * 1024 * 1024),
        ("grpc.max_receive_message_length", 64 * 1024 * 1024),
    ]
    return grpc.insecure_channel(server_addr, options=options)


def _make_fake_obs(step: int) -> dict:
    """Random obs dict matching the bi_so_follower + robot.env camera format."""
    rng = np.random.default_rng(step)
    return {
        **{k: float(rng.uniform(-50, 50)) for k in MOTOR_NAMES},
        "left_wrist":  rng.integers(0, 256, (480,  640,  3), dtype=np.uint8),
        "right_wrist": rng.integers(0, 256, (480,  640,  3), dtype=np.uint8),
        "right_front": rng.integers(0, 256, (720, 1280,  3), dtype=np.uint8),
        "task": "Fold the Garment",
    }


def _send_obs_stream(obs_bytes: bytes):
    """Yield gRPC Observation chunks (begin + end, no middle for simplicity)."""
    # Split into two chunks so the streaming protocol is exercised.
    mid = len(obs_bytes) // 2
    yield services_pb2.Observation(transfer_state=_TRANSFER_BEGIN, data=obs_bytes[:mid])
    yield services_pb2.Observation(transfer_state=_TRANSFER_END,   data=obs_bytes[mid:])


# ---------------------------------------------------------------------------
# Test stages
# ---------------------------------------------------------------------------

def stage1_handshake(stub: services_pb2_grpc.AsyncInferenceStub, server_addr: str) -> bool:
    """Ping Ready() and SendPolicyInstructions() — verifies gRPC transport."""
    print(f"\n[Stage 1] Handshake with {server_addr}")

    try:
        stub.Ready(services_pb2.Empty(), timeout=5)
        print("  ✓ Ready() — server accepted connection")
    except grpc.RpcError as e:
        print(f"  ✗ Ready() failed: {e.code()}: {e.details()}")
        return False

    try:
        cfg = RemotePolicyConfig(
            policy_type="test",
            pretrained_name_or_path="mock://test",
            lerobot_features=LEROBOT_FEATURES,
            actions_per_chunk=20,
            device="cpu",
        )
        stub.SendPolicyInstructions(
            services_pb2.PolicySetup(data=pickle.dumps(cfg)), timeout=10
        )
        print("  ✓ SendPolicyInstructions() — server accepted config")
    except grpc.RpcError as e:
        print(f"  ✗ SendPolicyInstructions() failed: {e.code()}: {e.details()}")
        return False

    return True


def stage2_obs_action_loop(
    stub: services_pb2_grpc.AsyncInferenceStub,
    n_steps: int,
    actions_per_chunk: int,
) -> bool:
    """Send N fake observations and verify the returned action chunks."""
    print(f"\n[Stage 2] obs→action loop  ({n_steps} steps, chunk={actions_per_chunk})")

    results: list[tuple[int, bool, str]] = []

    for step in range(n_steps):
        obs = _make_fake_obs(step)
        timed_obs = TimedObservation(
            timestamp=time.time(),
            timestep=step,
            observation=obs,
            must_go=True,
        )
        obs_bytes = pickle.dumps(timed_obs)

        # SendObservations
        try:
            stub.SendObservations(_send_obs_stream(obs_bytes), timeout=10)
        except grpc.RpcError as e:
            results.append((step, False, f"SendObservations error: {e.code()}: {e.details()}"))
            continue

        # GetActions
        t0 = time.perf_counter()
        try:
            response = stub.GetActions(services_pb2.Empty(), timeout=15)
        except grpc.RpcError as e:
            results.append((step, False, f"GetActions error: {e.code()}: {e.details()}"))
            continue
        rtt_ms = (time.perf_counter() - t0) * 1000

        if not response.data:
            results.append((step, False, "GetActions returned empty data (server queue may be empty)"))
            continue

        actions: list[TimedAction] = pickle.loads(response.data)

        # Validate
        if len(actions) != actions_per_chunk:
            results.append((
                step, False,
                f"wrong chunk length: got {len(actions)}, expected {actions_per_chunk}"
            ))
            continue

        a0 = actions[0].get_action()
        if not isinstance(a0, torch.Tensor):
            results.append((step, False, f"action[0] is {type(a0).__name__}, expected torch.Tensor"))
            continue
        if tuple(a0.shape) != (ACTION_DIM,):
            results.append((step, False, f"wrong action shape: {tuple(a0.shape)}, expected ({ACTION_DIM},)"))
            continue
        if a0.dtype != torch.float32:
            results.append((step, False, f"wrong dtype: {a0.dtype}, expected torch.float32"))
            continue

        vals = " ".join(f"{v:+.1f}" for v in a0.tolist())
        print(f"  Step {step:2d}: {len(actions)} actions  shape=({ACTION_DIM},)  rtt={rtt_ms:.0f}ms  [{vals}]")
        results.append((step, True, ""))

    passed = sum(1 for _, ok, _ in results if ok)
    failed = [(s, msg) for s, ok, msg in results if not ok]

    print(f"\n  {passed}/{n_steps} steps passed")
    for step, msg in failed:
        print(f"  ✗ Step {step}: {msg}")

    return len(failed) == 0


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def _print_summary(stage: int, s1_ok: bool | None, s2_ok: bool | None) -> bool:
    all_ok = True
    print("\n" + "=" * 56)
    print("  TEST SUMMARY")
    print("=" * 56)

    if s1_ok is not None:
        status = "PASS ✓" if s1_ok else "FAIL ✗"
        print(f"  Stage 1 — Handshake            : {status}")
        if not s1_ok:
            all_ok = False
            print("    → Check that your Docker is running and port 8080 is mapped.")
            print("    → Run: docker run --rm -p 8080:8080 <your-image>")
            print("    → Then retry: python test_client.py --server_addr=localhost:8080 --stage=1")

    if s2_ok is not None:
        status = "PASS ✓" if s2_ok else "FAIL ✗"
        print(f"  Stage 2 — obs→action loop      : {status}")
        if not s2_ok:
            all_ok = False
            print("    → Make sure _predict() returns a list of torch.Tensor(12,) float32.")
            print("    → Check server logs for tracebacks: docker logs <container-id>")

    print("=" * 56)
    if all_ok:
        print("  RESULT: ALL TESTS PASSED — your server is ready for evaluation.")
    else:
        print("  RESULT: SOME TESTS FAILED — see details above.")
    print("=" * 56 + "\n")
    return all_ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="LeHome policy server smoke test")
    ap.add_argument(
        "--server_addr", default="localhost:8080",
        help="host:port of the running policy server (default: localhost:8080)",
    )
    ap.add_argument(
        "--stage", type=int, choices=[1, 2], default=2,
        help="1=handshake only, 2=full obs→action loop (default: 2)",
    )
    ap.add_argument("--n_steps",          type=int, default=5,  help="round-trips for stage 2 (default: 5)")
    ap.add_argument("--actions_per_chunk", type=int, default=20, help="expected actions per chunk (default: 20)")
    args = ap.parse_args()

    print(f"LeHome Policy Server Test  —  target: {args.server_addr}  stage: {args.stage}")

    channel = _grpc_channel(args.server_addr)
    stub    = services_pb2_grpc.AsyncInferenceStub(channel)

    s1_ok: bool | None = None
    s2_ok: bool | None = None

    try:
        # Stage 1 always runs first (stage 2 includes it implicitly via Ready())
        s1_ok = stage1_handshake(stub, args.server_addr)

        if args.stage == 2 and s1_ok:
            s2_ok = stage2_obs_action_loop(stub, args.n_steps, args.actions_per_chunk)
        elif args.stage == 2 and not s1_ok:
            print("\n[Stage 2] Skipped — stage 1 failed.")

    finally:
        channel.close()

    all_ok = _print_summary(args.stage, s1_ok, s2_ok)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
