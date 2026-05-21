# LeHome Challenge — Contestant Guide

This guide explains how to package your policy model as a Docker image, test it locally, and submit it for evaluation.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Quick Start — 5 Steps](#2-quick-start--5-steps)
3. [Protocol Reference](#3-protocol-reference)
4. [Modifying server.py](#4-modifying-serverpy)
5. [Modifying Dockerfile](#5-modifying-dockerfile)
6. [Local Testing](#6-local-testing)
7. [Submission Checklist](#7-submission-checklist)
8. [Hardware Testing](#8-hardware-testing-optional--if-you-have-access-to-the-robot)
9. [FAQ](#9-faq)

---

## 1. System Overview

At evaluation time your Docker image runs on the organizer's machine. The robot client connects to it via gRPC and drives a real bimanual robot arm:

```
Organizer machine (robot client)             Your Docker (policy server)
┌─────────────────────────────────┐  gRPC   ┌──────────────────────────┐
│  eval_client.py                 │──obs───▶│  server.py               │
│  Dual-arm SO follower           │         │  Your model              │
│  3 cameras (L wrist/R wrist/    │◀─acts───│  port 8080               │
│            front)               │         │                          │
└─────────────────────────────────┘         └──────────────────────────┘
         localhost:8080
```

Each control cycle the robot sends you **one observation** (joint states + camera images) and you return **one action chunk** (a list of future joint positions). Your model must be loaded and ready before the robot connects — there is no model-load step during evaluation.

---

## 2. Quick Start — 5 Steps

```bash
# 1. Copy the template directory to your workspace
cp -r docker/policy_server/ my_policy/

# 2. Edit my_policy/server.py  — load your model in __init__, run it in _predict()
# 3. Edit my_policy/Dockerfile / requirements.txt  — add your dependencies

# 4. Build
docker build -t lehome-policy-myteam my_policy/

# 5. Test (one command)
bash scripts/test_policy.sh lehome-policy-myteam
```

If you see `RESULT: PASS` you are ready to submit.

---

## 3. Protocol Reference

### 3.1 Observation — what the robot sends you

Each call to `SendObservations` delivers one pickled `TimedObservation`. Inside `_predict(obs)` you receive its `.observation` dict with these keys:

#### Joint state (12 floats, units ≈ motor degrees)

| Key | Joint | Typical range |
|-----|-------|---------------|
| `left_shoulder_pan.pos`  | Left arm — shoulder rotate  | ~[−100, 100] |
| `left_shoulder_lift.pos` | Left arm — shoulder lift    | ~[−100, 100] |
| `left_elbow_flex.pos`    | Left arm — elbow bend       | ~[−100, 100] |
| `left_wrist_flex.pos`    | Left arm — wrist bend       | ~[−100, 100] |
| `left_wrist_roll.pos`    | Left arm — wrist roll       | ~[−100, 100] |
| `left_gripper.pos`       | Left gripper                | 0 = open, 100 = closed |
| `right_shoulder_pan.pos` | Right arm — shoulder rotate | ~[−100, 100] |
| `right_shoulder_lift.pos`| Right arm — shoulder lift   | ~[−100, 100] |
| `right_elbow_flex.pos`   | Right arm — elbow bend      | ~[−100, 100] |
| `right_wrist_flex.pos`   | Right arm — wrist bend      | ~[−100, 100] |
| `right_wrist_roll.pos`   | Right arm — wrist roll      | ~[−100, 100] |
| `right_gripper.pos`      | Right gripper               | 0 = open, 100 = closed |

#### Camera images (numpy `uint8`, RGB, HWC layout)

| Key | Shape | Camera |
|-----|-------|--------|
| `left_wrist`  | `(480, 640, 3)`  | Left wrist camera |
| `right_wrist` | `(480, 640, 3)`  | Right wrist camera |
| `right_front` | `(720, 1280, 3)` | Front / overhead camera |

#### Task string

| Key | Example |
|-----|---------|
| `task` | `"Fold the Garment"` |

### 3.2 Action — what you must return

`GetActions` must return `list[TimedAction]`. Each element's `.action` must be a **`torch.Tensor` of shape `(12,)` and dtype `float32`**.

Index-to-joint mapping:

```
index  0  left_shoulder_pan.pos       6  right_shoulder_pan.pos
       1  left_shoulder_lift.pos      7  right_shoulder_lift.pos
       2  left_elbow_flex.pos         8  right_elbow_flex.pos
       3  left_wrist_flex.pos         9  right_wrist_flex.pos
       4  left_wrist_roll.pos        10  right_wrist_roll.pos
       5  left_gripper.pos           11  right_gripper.pos
```

The list length must equal `actions_per_chunk` (default **20**).

### 3.3 Call sequence (for reference)

```
1. Ready()                       → handshake, returns Empty
2. SendPolicyInstructions(data)  → config metadata, returns Empty (you may ignore it)
3. Loop per control step:
   a. SendObservations(stream)   → one observation frame, returns Empty
   b. GetActions(Empty)          → returns your action chunk
```

---

## 4. Modifying server.py

You only need to touch two places, both marked with `# [CONTESTANT]`.

### 4.1 Load your model — `__init__`

```python
def __init__(self, fps: int, chunk: int):
    super().__init__(fps, chunk)
    ...
    # [CONTESTANT] Load your model here.
    self.model = YourModel.from_pretrained("/app/checkpoints")
    self.model.eval()
    # Optional but recommended: run one warm-up forward pass to avoid
    # a long delay on the very first GetActions call.
    dummy_obs = {k: 0.0 for k in MOTOR_NAMES}
    self._predict(dummy_obs)
    log.info("Model loaded and warmed up.")
```

### 4.2 Run inference — `_predict`

```python
def _predict(self, obs: dict) -> list[torch.Tensor]:
    # Extract joint state
    state = torch.tensor(
        [obs.get(k, 0.0) for k in MOTOR_NAMES], dtype=torch.float32
    )

    # Extract and preprocess images  (RGB uint8 HWC → float32 CHW in [0, 1])
    def to_tensor(img: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(img).float().div(255).permute(2, 0, 1)

    left_wrist  = to_tensor(obs["left_wrist"])   # shape (3, 480, 640)
    right_wrist = to_tensor(obs["right_wrist"])  # shape (3, 480, 640)
    front       = to_tensor(obs["right_front"])  # shape (3, 720, 1280)

    with torch.no_grad():
        actions = self.model(state, left_wrist, right_wrist, front)
        # actions must be a tensor of shape (chunk, 12)

    return list(actions)  # list of Tensor(12,), length == self.chunk
```

**Constraints:**
- Return exactly `self.chunk` tensors (default 20).
- Each tensor must be `torch.float32`, shape `(12,)`.
- Stay within 200 ms per `_predict` call. The robot times out after 5 s of waiting; missed deadlines cause arm pauses.

---

## 5. Modifying Dockerfile

### 5.1 CPU-only (no GPU needed)

The default template works out of the box:

```dockerfile
FROM python:3.12-slim
...
# requirements.txt already uses CPU-only torch
```

### 5.2 CUDA / GPU

Replace the base image and remove the `--extra-index-url` from `requirements.txt`:

```dockerfile
# Dockerfile — change this line:
FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime
```

```text
# requirements.txt — replace the torch line:
grpcio>=1.73.1
grpcio-tools>=1.73.1
protobuf>=5.0
torch>=2.0          # no --extra-index-url; the base image already has CUDA torch
numpy>=1.24
```

Run with GPU access at evaluation:
```bash
docker run --rm --gpus all -p 8080:8080 lehome-policy-myteam
```

### 5.3 Copying your model weights

```dockerfile
# [CONTESTANT] Copy your checkpoint files into the image:
COPY checkpoints/ /app/checkpoints/
```

Keep the protocol files section unchanged — they must be present:
```dockerfile
# Do not modify these lines:
COPY services_pb2.py        /app/
COPY services_pb2_grpc.py   /app/
COPY protocol.py            /app/
COPY server.py              /app/
COPY entrypoint.sh          /app/
```

### 5.4 Adding extra Python packages

Add them to `requirements.txt` before building, or add a `RUN pip install ...` line in the Dockerfile.

---

## 6. Local Testing

### 6.1 One-command test (recommended)

Requires Docker and Python 3 with `grpcio numpy torch` on your host:

```bash
# Install test dependencies once (if not already installed):
pip install grpcio>=1.73.1 numpy torch

# Run the full test:
bash scripts/test_policy.sh lehome-policy-myteam
```

The script will:
1. Start your Docker container.
2. Wait for the server to be ready (up to 20 s).
3. Run Stage 1 (handshake) and Stage 2 (5 obs→action round-trips).
4. Stop the container and print `PASS` or `FAIL`.

### 6.2 Manual step-by-step

```bash
# Terminal A — start your Docker:
docker run --rm -p 8080:8080 lehome-policy-myteam
# Wait until you see: "Policy server listening on 0.0.0.0:8080"

# Terminal B — Stage 1: handshake only
python docker/policy_server/test_client.py --server_addr=localhost:8080 --stage=1

# Terminal B — Stage 2: full obs→action loop
python docker/policy_server/test_client.py --server_addr=localhost:8080 --stage=2
```

### 6.3 Verify GPU is visible (if applicable)

```bash
docker run --rm --gpus all lehome-policy-myteam \
    python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

---

## 7. Submission Checklist

Before submitting, confirm all of the following:

- [ ] `bash scripts/test_policy.sh lehome-policy-myteam` prints **PASS**
- [ ] Model weights are baked into the image (not downloaded at runtime)
- [ ] No secrets, API keys, or large unrelated files in the image
- [ ] If using GPU: `torch.cuda.is_available()` returns `True` inside Docker
- [ ] Your `_predict()` returns `self.chunk` tensors of shape `(12,)` dtype `float32`
- [ ] Inference time is well under 200 ms per step

**Export your image:**
```bash
docker save lehome-policy-myteam | gzip > lehome-policy-myteam.tar.gz
```

Tell the organizer:
- Whether `--gpus all` is required
- Your team name (used as the image tag)

---

## 8. Hardware Testing (Optional — if you have access to the robot)

If you have access to an SO-100 bimanual robot setup, you can run your policy Docker against real hardware before submitting. This gives far more confidence than fake-observation testing.

### 8.1 Prerequisites

Complete the full environment setup first:

```bash
# 1. Install the project Python environment
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e "./third_party/lerobot[all]"

# 2. Configure hardware ports and cameras
cp robot.env.template robot.env
nano robot.env        # fill in your serial port paths and camera indices
# See doc/02_robot_env.md for how to find the right device paths
```

### 8.2 Verify hardware wiring with the mock server

Before connecting your real policy, use the **mock server** to confirm the robot responds to commands. This runs entirely within the project venv — no Docker required.

```bash
# Terminal A — hold-position mock (arms don't move, safe):
source .venv/bin/activate
python scripts/mock_policy_server.py --port=8080

# Terminal B — run the hardware eval client:
source .venv/bin/activate
source ./robot.env
export TEAM=test TASK="Fold the Garment" N_EPISODES=1 EPISODE_DURATION=10
bash scripts/start_eval_client.sh
```

If the arms hold their current position and the client prints step logs, the hardware pipeline is working. Then try the sine-wave demo:

```bash
# Terminal A — sine-wave demo (arms will oscillate slowly):
python scripts/mock_policy_server.py --port=8080 --demo --amplitude=5 --period=6
```

**Keep `--amplitude` small (≤ 10°) and make sure the arms have clearance.**

### 8.3 Test your Docker policy on real hardware

Once the mock test passes, replace the mock server with your policy Docker:

```bash
# Terminal A — your policy Docker:
docker run --rm -p 8080:8080 lehome-policy-myteam
# Wait for: "Policy server listening on 0.0.0.0:8080"

# Terminal B — hardware eval client (same as before):
source .venv/bin/activate
source ./robot.env
export TEAM=myteam N_EPISODES=2 EPISODE_DURATION=30
bash scripts/start_eval_client.sh
```

**Keyboard controls during evaluation:**

| Key | Effect |
|-----|--------|
| `→` or `d` | Finish current episode early, proceed to next |
| `←` or `a` | Abort current episode and **redo** it (scene wasn't ready, robot fell, etc.) |
| `ESC` | Stop the entire session |

Between episodes the script waits for **ENTER** before starting the next one, giving the operator time to reset the scene.

What happens each episode:
1. Print episode banner with key hints.
2. Prompt **ENTER** — operator resets scene, then presses ENTER.
3. Control loop runs until `EPISODE_DURATION` seconds elapse **or** operator presses `→` / `←`:
   - Captures joint state + camera images from the real robot.
   - Sends them to your Docker via gRPC.
   - Receives predicted action chunk, executes on arms at 20 Hz.
   - Keyboard events are checked between every action (≤ 50 ms response time).
4. Front-camera frames are saved to `Datasets/eval/<team>/<task>/`.

### 8.4 Environment variable reference

| Variable | Default | Description |
|----------|---------|-------------|
| `TEAM` | `test_run` | Used in output filenames |
| `TASK` | `Fold the Garment` | Task string sent to the policy |
| `N_EPISODES` | `2` | Number of evaluation episodes |
| `EPISODE_DURATION` | `60` | Seconds per episode |
| `SERVER_ADDR` | `localhost:8080` | Policy Docker address |
| `FPS` | `20` | Control frequency (Hz) |
| `ACTIONS_PER_CHUNK` | `20` | Actions returned per gRPC call |

### 8.5 Troubleshooting hardware tests

**`LEFT_FOLLOWER_PORT` not set**
→ Run `source ./robot.env` before calling `start_eval_client.sh`.

**`make_robot` or `make_robot` import error**
→ Activate the venv first: `source .venv/bin/activate`.

**Arms hold position but don't move**
→ This is the default behavior of `server.py` — the template echoes joint state. Replace `_predict()` with your model.

**`GetActions` timeout — arms pause**
→ Your model inference takes > 5 s. Add a warm-up call in `__init__` (see §4.1).

**Camera image shape mismatch**
→ Confirm `robot.env` camera resolutions match what the policy expects (`left_wrist`: 480×640, `right_wrist`: 480×640, `right_front`: 720×1280).

---

## 9. FAQ

### Server startup

**Q: The server crashes immediately with a RuntimeError about grpcio version.**

```
RuntimeError: The grpc package installed is at version X.Y.Z,
but the generated code ... depends on grpcio>=1.73.1.
```

→ Your `requirements.txt` has an older `grpcio` pin. Change it to `grpcio>=1.73.1` and rebuild the image.

---

**Q: `docker run` exits immediately with no output.**

→ Run without `--rm` to keep the container after exit, then check logs:
```bash
docker run -p 8080:8080 lehome-policy-myteam
docker logs <container-id>
```
Look for a Python traceback — usually a missing dependency or an import error in your model code.

---

**Q: The server starts but `test_policy.sh` reports "Server did not print 'listening' within 20 s".**

→ Your model is taking a long time to load (large checkpoint). Either increase the timeout in `test_policy.sh` (change `seq 1 40` to a larger number) or add a faster loading path. For evaluation the organizer will wait for the server to be ready before connecting the robot.

---

### Communication errors

**Q: Stage 1 fails with `StatusCode.UNAVAILABLE`.**

→ The client cannot reach the server. Check:
```bash
# Is the container running?
docker ps
# Is port 8080 mapped?
docker run --rm -p 8080:8080 lehome-policy-myteam
# Did the server actually start listening?
docker logs <container-id> | grep listening
```

---

**Q: Stage 1 fails with `StatusCode.DEADLINE_EXCEEDED`.**

→ The server started but is not responding to `Ready()` in time — usually because it is still loading the model. Add a warmup call at the end of `__init__` (see §4.1) so the model is fully ready before the first gRPC call.

---

**Q: Port 8080 is already in use.**

```bash
# Find and kill the process holding the port:
ss -tlnp | grep 8080
kill -9 <PID>
```
Or use a different port: `bash scripts/test_policy.sh lehome-policy-myteam 8081`.

---

### Action validation failures

**Q: Stage 2 fails with "wrong action shape".**

→ Your `_predict()` is returning tensors of the wrong size. It must return a list of tensors each of shape `(12,)`. Common mistakes:
- Returning a single `(chunk, 12)` tensor instead of a list.
- Returning `(1, 12)` tensors instead of `(12,)`.
- Forgetting to trim to exactly `self.chunk` elements.

---

**Q: Stage 2 fails with "wrong dtype: torch.float64".**

→ Add `.float()` when constructing your action tensor:
```python
action = model_output.float()   # ensure float32
```

---

**Q: Stage 2 fails with "GetActions returned empty data".**

→ The server's observation queue was empty when `GetActions` was called. This happens if `SendObservations` raised an exception before putting the observation in the queue. Check the server logs for a traceback in `SendObservations`.

---

### Performance

**Q: The arms pause or stutter during evaluation.**

→ `GetActions` times out after **5 seconds** — if your model takes longer the robot waits. Target **< 200 ms** per inference step. Tips:
- Call `model.eval()` and use `torch.no_grad()` in `_predict()`.
- Run a warm-up forward pass in `__init__` to JIT-compile kernels before the robot connects.
- Use half-precision (`model.half()`) if your GPU supports it.

---

**Q: GPU OOM error during inference.**

→ Add `torch.cuda.empty_cache()` at the end of `_predict()`, ensure you are using `torch.no_grad()`, and check that `model.eval()` is called in `__init__`.

---

### Image / observation issues

**Q: My model expects a different image resolution.**

→ Resize inside `_predict()` before passing to your model:
```python
import torch.nn.functional as F
img = to_tensor(obs["left_wrist"])        # (3, 480, 640)
img = F.interpolate(img.unsqueeze(0), size=(224, 224)).squeeze(0)
```

---

**Q: I get a pickle `AttributeError: Can't get attribute 'TimedObservation'`.**

→ Do not modify `protocol.py`. The pickle compat layer in `server.py` maps the lerobot class names to your local `protocol.py` classes. If you renamed or moved `protocol.py` this mapping breaks.

---

**Q: The task string is always `"Fold the Garment"` — is that correct?**

→ Yes, for this challenge the task is fixed. Your model may ignore the `task` key or use it as a language condition.
