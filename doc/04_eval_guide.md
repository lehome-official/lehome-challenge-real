# Evaluation Operations Guide (Internal)

This document is for the **evaluation team**. It describes the full procedure for running on-hardware evaluations.

## 1. System Architecture

```
Local machine (robot arm)                    Local machine (contestant Docker)
┌──────────────────────────────┐  gRPC  ┌──────────────────────────┐
│  scripts/start_eval_client.sh│──obs──▶│  Contestant policy server │
│  eval_client.py              │        │  Docker image             │
│  bi_so_follower dual arm     │◀─acts──│  Contestant model         │
│  3 cameras                   │        │  port 8080               │
│  Front camera .mp4 backup    │        └──────────────────────────┘
└──────────────────────────────┘
```

## 2. Environment setup (one-time)

```bash
source .venv/bin/activate
source ./robot.env

# Confirm the user is in the dialout group (serial port access)
groups | grep dialout
# If not listed: sudo usermod -aG dialout $USER  then re-login
```

## 3. Evaluation procedure

### 3.1 Start the contestant's Docker

```bash
sudo docker run --rm -p 8080:8080 <contestant-image-name>
# Wait until the log shows: "Policy server listening on 0.0.0.0:8080"
```

> If you get `address already in use`, find and kill the process holding the port:
> ```bash
> ss -tlnp | grep 8080
> kill -9 <PID>
> ```

### 3.2 Start the evaluation client

```bash
cd /home/ubuntu/Desktop/lehome-challenge-real
source .venv/bin/activate
source ./robot.env
export DISPLAY=:0

export TEAM=team_alpha          # contestant team identifier
export TASK="Fold the Garment"  # evaluation task
export N_EPISODES=2             # number of episodes
export EPISODE_DURATION=60      # seconds per episode

bash scripts/start_eval_client.sh
```

During evaluation:
- The program waits for **ENTER** before each episode so the operator can reset the scene.
- The front camera records **continuously** for the entire evaluation session (one MP4 file per run).
- Press **Ctrl-C** at any time to stop; already-recorded video is saved normally.

### 3.3 Validate a contestant's Docker (no real robot required)

Use the gRPC test script to confirm communication before connecting the real hardware:

```bash
# Terminal A — start the contestant's Docker
sudo docker run --rm -p 8080:8080 <contestant-image-name>

# Terminal B — Stage 1: gRPC handshake
source .venv/bin/activate
python scripts/test_grpc.py --stage=1 --server_addr=localhost:8080

# Terminal B — Stage 2: full obs→action round-trip (fake observations, checks action shape=(12,))
python scripts/test_grpc.py --stage=2 --server_addr=localhost:8080
```

Connect the real robot only after both stages pass.

### 3.4 Debug with the mock server (no contestant Docker required)

```bash
# Terminal A — sine-wave mock server (arms will move visibly)
source .venv/bin/activate
python scripts/mock_policy_server.py --port=8080 --demo --amplitude=10 --period=6

# Terminal B — evaluation client (connects to real robot)
source ./robot.env
export DISPLAY=:0
TEAM=test_run bash scripts/start_eval_client.sh
```

Running without `--demo` produces hold-position actions (safe, arms do not move) — useful for testing the communication path without robot motion.

## 4. Data storage

```
Datasets/eval/
└── <team>/
    └── <task_slug>/
        └── <task_slug>_<team>_<YYYYMMDD_HHMMSS>.mp4
```

The front (overhead) camera records continuously from the first episode until the evaluation ends or Ctrl-C is pressed. One MP4 file is produced per evaluation run.

## 5. Evaluation parameters quick reference

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `TEAM` | **required** | Team identifier (used in filenames) |
| `SERVER_ADDR` | `localhost:8080` | Contestant server address |
| `TASK` | `Fold the Garment` | Task description string |
| `N_EPISODES` | `5` | Number of evaluation episodes |
| `EPISODE_DURATION` | `60` | Seconds per episode |
| `FPS` | `20` | Control frequency (Hz) |
| `ACTIONS_PER_CHUNK` | `20` | Actions returned per server call |

## 6. Troubleshooting

**Port already in use**
`ss -tlnp | grep 8080` → find the PID → `kill -9 <PID>` → restart Docker.

**Connection failure — `UNAVAILABLE`**
Confirm the Docker log shows `listening on 0.0.0.0:8080` and that `-p 8080:8080` is present in the `docker run` command.

**Arms not moving**
Check the server log for `GetActions` output. `GetActions` times out after 5 s and returns empty — arms pause. Validate the communication path first with `test_grpc.py --stage=2`.

**Video file empty or corrupted**
Confirm `source ./robot.env` was run before starting the client. The Orbbec front camera needs `warmup_s: 5` (~2.5 s warm-up) before delivering its first frame.

**All actions hold position**
This is the default behavior of the template `server.py` (safe placeholder). It is expected until the contestant replaces it with a real model. Use `mock_policy_server.py --demo` to verify arm motion independently.
