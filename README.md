# LeHome Challenge

Bimanual robot manipulation competition. You train a policy, package it as a Docker image, and submit it. At evaluation time the robot client sends real joint states and camera images to your Docker via gRPC and executes the actions your model returns.

```
Robot (organizer machine)              Policy server (your Docker)
┌──────────────────────────┐  gRPC    ┌──────────────────────────┐
│  Dual-arm SO follower    │──obs────▶│  server.py               │
│  3 cameras               │◀─actions─│  Your model              │
│  localhost:8080          │          │  port 8080               │
└──────────────────────────┘          └──────────────────────────┘
```

---

## For Contestants — package and test your policy

### Quick Start (5 steps)

```bash
# 1. Copy the template
cp -r docker/policy_server/ my_policy/

# 2. Edit my_policy/server.py  — load your model in __init__, run it in _predict()
# 3. Edit my_policy/Dockerfile — add your dependencies, copy your model weights

# 4. Build
docker build -t lehome-policy-myteam my_policy/

# 5. Test end-to-end with fake observations (no hardware needed)
bash scripts/test_policy.sh lehome-policy-myteam
```

`RESULT: PASS` means your image is ready to submit.

**Full guide:** [doc/contestant_guide.md](doc/contestant_guide.md) — protocol reference, model integration examples, GPU setup, submission checklist, FAQ.

### Submit

```bash
docker save lehome-policy-myteam | gzip > lehome-policy-myteam.tar.gz
```

Send the `.tar.gz` to the organizers and tell them whether `--gpus all` is required.

---

## For Organizers — run evaluation at the competition

**Full guide:** [doc/04_eval_guide.md](doc/04_eval_guide.md) (English) · [doc/04_eval_guide_zh.md](doc/04_eval_guide_zh.md) (中文)

The guide covers one-time machine setup, hardware verification, per-contestant evaluation procedure, keyboard controls, and troubleshooting. Reading time: ~10 minutes.

### Evaluation in brief

```
One-time setup:
  1. Clone repo + install lerobot environment (doc/01_environment.md)
  2. Configure robot ports and cameras in robot.env (doc/02_robot_env.md)
  3. Verify hardware with mock server (doc/04_eval_guide.md §2)

Per contestant:
  4. docker load < lehome-policy-teamname.tar.gz
  5. docker run --rm -p 8080:8080 lehome-policy-teamname
  6. TEAM=teamname N_EPISODES=5 bash scripts/start_eval_client.sh

Keyboard controls during evaluation:
  → or d    finish episode early, go to next
  ← or a    abort and redo this episode
  ESC       stop the session
  ENTER     (at prompt) scene is ready, start next episode
```

---

## Repository Layout

```
docker/policy_server/     ← Contestant: copy, modify, and submit this
  server.py               ← Implement _predict() with your model
  Dockerfile              ← Add deps and copy weights here
  requirements.txt        ← Python dependencies
  protocol.py             ← Data classes — do not modify
  services_pb2*.py        ← gRPC stubs — do not modify
  entrypoint.sh           ← Docker startup — do not modify
  test_client.py          ← Smoke test client (runs inside test_policy.sh)

scripts/
  test_policy.sh          ← Contestant: one-command Docker smoke test
  eval_client.py          ← Organizer: hardware evaluation client
  start_eval_client.sh    ← Organizer: evaluation session launcher
  mock_policy_server.py   ← Organizer: hardware verification (no model needed)

robot.env.template        ← Copy to robot.env and fill in device paths

doc/
  contestant_guide.md     ← Full contestant guide
  04_eval_guide.md        ← Full organizer / competition day guide (EN)
  04_eval_guide_zh.md     ← Full organizer / competition day guide (中文)
  01_environment.md       ← Python environment setup
  02_robot_env.md         ← Serial port and camera configuration
  03_bimanual_record.md   ← Data collection for training
```
