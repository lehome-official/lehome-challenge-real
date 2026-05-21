# Competition Day Evaluation Guide (Organizer)

This is the definitive guide for running on-hardware evaluations. Follow it top-to-bottom on a fresh machine and you will be ready to evaluate contestants without touching any other document.

---

## 0. Pre-flight Checklist

Before the competition starts, confirm all of these once:

- [ ] Docker is installed: `docker --version`
- [ ] Python 3.12 environment is set up (§1.1)
- [ ] `robot.env` is filled in with correct device paths (§1.2)
- [ ] Current user is in the `dialout` group (§1.3)
- [ ] Hardware test with mock server passed (§1.4)
- [ ] `DISPLAY=:0` works (keyboard listener active during hardware test)

---

## 1. One-Time Machine Setup

Run this once on a fresh machine before the competition.

### 1.1 Clone the repo and install the environment

```bash
git clone <repo-url> lehome-challenge-real
cd lehome-challenge-real

# Create Python 3.12 virtual environment
uv venv --python 3.12
source .venv/bin/activate

# Install LeRobot with all extras
uv pip install -e "./third_party/lerobot[all]"
```

> If `uv` is not installed: `pip install uv`
>
> If `third_party/lerobot` is empty: `git clone https://github.com/huggingface/lerobot.git third_party/lerobot` then re-run the pip command.

Verify:
```bash
python -c "import lerobot; print('lerobot ok')"
```

### 1.2 Configure hardware ports and cameras

```bash
cp robot.env.template robot.env
nano robot.env   # or use any editor
```

Plug in arms one at a time to identify stable serial port IDs:
```bash
ls -l /dev/serial/by-id/
```

Fill in `robot.env` with the actual paths:
```bash
export LEFT_FOLLOWER_PORT=/dev/serial/by-id/usb-LEFT_FOLLOWER_...
export RIGHT_FOLLOWER_PORT=/dev/serial/by-id/usb-RIGHT_FOLLOWER_...
export LEFT_WRIST_CAMERA_INDEX=0   # or /dev/v4l/by-id/...
export RIGHT_WRIST_CAMERA_INDEX=1
export FRONT_CAMERA_INDEX=2
# (widths/heights/fps already filled to defaults in the template)
```

Full instructions: [02_robot_env.md](02_robot_env.md)

### 1.3 Serial port permissions

```bash
groups | grep dialout
```

If `dialout` is not listed:
```bash
sudo usermod -aG dialout $USER
```

Then **log out and back in** (or reboot). Verify with `groups` again.

### 1.4 Verify hardware with the mock server

This step confirms the robot responds to commands **before** connecting any contestant's policy. The arms will hold position (not move).

**Terminal A — start mock server (hold position, safe):**
```bash
source .venv/bin/activate
python scripts/mock_policy_server.py --port=8080
```

**Terminal B — run the eval client:**
```bash
cd lehome-challenge-real
source .venv/bin/activate
source ./robot.env
export DISPLAY=:0

TEAM=hardware_test N_EPISODES=1 EPISODE_DURATION=10 \
bash scripts/start_eval_client.sh
```

Expected output in Terminal B:
```
===========================================================
  Episode 1/1   task: Fold the Garment
  Keys:  →/d finish    ←/a redo    ESC stop all
===========================================================
  Reset the scene, then press ENTER to start ...
```

Press ENTER. Watch the step logs appear. Confirm:
- Arms hold their current position (no movement — mock server is hold-position mode)
- Keyboard keys respond: press `→` to finish the episode early
- Video file appears in `Datasets/eval/hardware_test/`

**Optional: test arm motion with sine-wave demo (arms will move visibly)**
```bash
# Terminal A — replace mock server with demo version:
python scripts/mock_policy_server.py --port=8080 --demo --amplitude=5 --period=6
```

Make sure arms have clearance before running `--demo`.

---

## 2. Per-Contestant Evaluation Procedure

Repeat this for each contestant. Takes ~5 minutes of setup + the actual evaluation time.

### 2.1 Load the contestant's Docker image

Contestants submit a `.tar.gz` file. Load it:

```bash
docker load < lehome-policy-teamname.tar.gz
```

The output shows the image name:
```
Loaded image: lehome-policy-teamname:latest
```

If the name is unclear, run `docker images` to see recently loaded images.

> **GPU:** If the contestant specified GPU is required, you will use `--gpus all` in step 2.3.

### 2.2 Verify the Docker before connecting the robot (30 seconds)

Run the Docker and the fake-observation test client simultaneously. This checks the gRPC protocol **without touching the real arms**.

```bash
# Terminal A — start contestant's Docker:
docker run --rm -p 8080:8080 lehome-policy-teamname
# Wait until you see: "Policy server listening on 0.0.0.0:8080"

# Terminal B — run the smoke test:
source .venv/bin/activate
python docker/policy_server/test_client.py \
    --server_addr=localhost:8080 --stage=2 --n_steps=3
```

Expected:
```
  Stage 1 — Handshake            : PASS ✓
  Stage 2 — obs→action loop      : PASS ✓
  RESULT: ALL TESTS PASSED
```

If either stage fails, **do not connect the real robot**. Share the error with the contestant for debugging.

### 2.3 Start the evaluation session

Stop the Terminal A Docker from 2.2 first (`Ctrl-C`), then:

```bash
# Terminal A — restart Docker (with GPU flag if contestant requires it):
docker run --rm -p 8080:8080 lehome-policy-teamname
# (GPU variant:)
# docker run --rm --gpus all -p 8080:8080 lehome-policy-teamname

# Wait for: "Policy server listening on 0.0.0.0:8080"
```

```bash
# Terminal B — start evaluation:
cd lehome-challenge-real
source .venv/bin/activate
source ./robot.env
export DISPLAY=:0

export TEAM=teamname           # contestant identifier (used in filenames)
export TASK="Fold the Garment"
export N_EPISODES=5            # number of evaluation episodes
export EPISODE_DURATION=60     # seconds per episode

bash scripts/start_eval_client.sh
```

### 2.4 Keyboard controls during evaluation

| Key | When to press | Effect |
|-----|---------------|--------|
| `→` or `d` | Task completed / robot failed / you want to end early | Episode ends, counted in results, moves to next |
| `←` or `a` | Scene wasn't reset properly / robot started from wrong position | Episode **not counted**, same episode number repeats |
| `ESC` | Emergency — stop everything | Session ends, video saved, robot stops |
| `ENTER` (at prompt) | Scene is reset and ready | Starts the next episode |

### 2.5 Episode flow

```
===========================================================
  Episode 1/5   task: Fold the Garment
  Max duration: 60 s
  Keys:  →/d finish    ←/a redo    ESC stop all
===========================================================
  Reset the scene, then press ENTER to start ...
```

1. **Physically reset** the scene (arrange the garment, home the arms if needed).
2. Press **ENTER** — robot starts moving.
3. Watch the episode. When done (success, failure, or 60s elapsed):
   - If valid result: press `→` or wait for timeout → counted as episode N, next episode begins.
   - If invalid (scene not ready, arm collision, etc.): press `←` → episode repeats with same number.
4. Repeat until all `N_EPISODES` are complete.

### 2.6 After evaluation

```bash
# Find the recorded video:
ls Datasets/eval/<teamname>/fold_the_garment/

# Stop the contestant's Docker (Terminal A):
Ctrl-C
```

Video file format: `fold_the_garment_<team>_<YYYYMMDD_HHMMSS>.mp4`

---

## 3. Quick Reference Card

```bash
# Source environment (run in every new terminal before any command)
source .venv/bin/activate && source ./robot.env && export DISPLAY=:0

# Load contestant Docker
docker load < lehome-policy-teamname.tar.gz

# Start Docker
docker run --rm -p 8080:8080 lehome-policy-teamname
# (GPU:)  docker run --rm --gpus all -p 8080:8080 lehome-policy-teamname

# Verify Docker (no hardware, 30 s)
python docker/policy_server/test_client.py --server_addr=localhost:8080 --stage=2

# Start evaluation
TEAM=teamname N_EPISODES=5 EPISODE_DURATION=60 bash scripts/start_eval_client.sh

# Hardware test with mock server (hold position)
python scripts/mock_policy_server.py --port=8080

# Hardware test with sine-wave demo (arms move)
python scripts/mock_policy_server.py --port=8080 --demo --amplitude=5 --period=6

# Kill process holding port 8080
ss -tlnp | grep 8080   # find PID
kill -9 <PID>
```

---

## 4. Environment Variable Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `TEAM` | **required** | Contestant team name (used in video filenames) |
| `TASK` | `Fold the Garment` | Task description sent to the policy |
| `N_EPISODES` | `2` | Number of evaluation episodes |
| `EPISODE_DURATION` | `60` | Maximum seconds per episode |
| `SERVER_ADDR` | `localhost:8080` | Policy Docker address |
| `FPS` | `20` | Control frequency — must match training data FPS |
| `ACTIONS_PER_CHUNK` | `20` | Actions per gRPC call — must match model's chunk_size |

`FPS` and `ACTIONS_PER_CHUNK` should match what the contestant used during training. When in doubt, ask the contestant. The defaults (20 / 20) are correct for most LeRobot ACT models trained at 20 Hz.

---

## 5. Troubleshooting

### Port 8080 already in use
```bash
ss -tlnp | grep 8080   # find PID
kill -9 <PID>
```
Then restart Docker.

### "Policy server listening" never appears
The model is taking a long time to load (large checkpoint). Wait up to 2 minutes. If it still doesn't appear, run without `--rm` to keep the container after exit and inspect the logs:
```bash
docker run -p 8080:8080 lehome-policy-teamname
docker logs <container-id>
```

### Stage 2 of test_client.py fails — wrong action shape or dtype
The contestant's `_predict()` is returning tensors with the wrong shape or type. Share the error message with the contestant for debugging. Do not connect the real robot.

### eval_client: "LEFT_FOLLOWER_PORT not set"
```bash
source ./robot.env   # must run in the same terminal as start_eval_client.sh
```

### eval_client: "LeRobot not found" or ImportError
```bash
source .venv/bin/activate   # must activate venv first
```

### Keyboard keys not responding
`pynput` needs a display. Ensure `DISPLAY=:0` is set:
```bash
export DISPLAY=:0
```
If running over SSH, use `ssh -X` or connect a physical display.

### Arms hold position but don't move
This is the **default behavior** of the contestant's template `server.py` — it echoes joint state until the contestant replaces `_predict()` with a real model. Check that the correct Docker image is running.

### Arms move but jerkily or stop partway through
The model's inference is slow (> 200 ms per step). The `GetActions` call times out after 5 s; if the model misses the deadline, the arms pause. Ask the contestant to add a warm-up pass in `__init__` and check their inference latency.

### Front camera warmup (video starts blank)
The Orbbec front camera needs ~5 s to deliver its first frame. The first few video frames may be black. This is normal — `warmup_s: 5` is already configured in the robot config.

### Video file is very short (episode was 60 s but video is 3 s)
This would indicate a bug in the eval_client. If you see this, check the `actions_per_chunk` value: it should equal the number of actions the model returns per call (default 20). If the model returns a different chunk size, set `ACTIONS_PER_CHUNK` accordingly before running.
