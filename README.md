# LeHome Challenge — Contestant Starter Kit

This repository contains everything you need to participate in the **LeHome Challenge** bimanual robot manipulation competition.

## Overview

You train a policy model and package it as a Docker image. At evaluation time, our robot client connects to your Docker container via gRPC, sends observations (joint states + camera images), and executes the actions your model returns.

```
Our robot (client)                     Your Docker (server)
┌──────────────────────────┐  gRPC    ┌──────────────────────────┐
│  Dual-arm SO robot       │──obs────▶│  server.py               │
│  3 cameras               │◀─actions─│  Your model              │
│  localhost:8080          │          │  port 8080               │
└──────────────────────────┘          └──────────────────────────┘
```

## Quick Start

```bash
# 1. Copy the template
cp -r docker/policy_server/ my_policy/

# 2. Edit my_policy/server.py  — integrate your model
# 3. Edit my_policy/Dockerfile — add dependencies and copy weights

# 4. Build
docker build -t lehome-policy-myteam my_policy/

# 5. Test end-to-end (one command)
bash scripts/test_policy.sh lehome-policy-myteam
```

`RESULT: PASS` means your image is ready to submit.

## Repository Layout

```
docker/policy_server/     ← Template to modify and submit
  Dockerfile              ← Change base image for GPU; add deps
  server.py               ← Implement _predict() with your model
  requirements.txt        ← Add your Python dependencies
  protocol.py             ← Data classes (do not modify)
  services_pb2*.py        ← gRPC stubs (do not modify)
  entrypoint.sh           ← Docker startup (do not modify)
  test_client.py          ← Standalone test client

scripts/
  test_policy.sh          ← One-script end-to-end test

doc/
  contestant_guide.md     ← Full guide (protocol, FAQ, examples)
  README.md               ← Doc index
```

## Documentation

Read [doc/contestant_guide.md](doc/contestant_guide.md) for:

- Complete observation / action protocol reference
- Step-by-step model integration examples
- CPU and GPU Docker setup
- Local testing instructions
- Submission checklist
- Detailed FAQ

## Submission

```bash
docker save lehome-policy-myteam | gzip > lehome-policy-myteam.tar.gz
```

Submit the `.tar.gz` to the organizers and specify whether `--gpus all` is required at runtime.
