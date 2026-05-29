# Environment Setup

This project uses `uv` to manage the Python environment. Python version is locked to `3.12`. LeRobot is cloned into `third_party/lerobot` and installed in editable mode with the `lerobot[all]` extras from the project root.

A [`uv.toml`](../uv.toml) is provided at the repo root, defaulting to the Tsinghua PyPI mirror for faster dependency resolution in China. If the Tsinghua mirror is unavailable, `uv` falls back to the official PyPI automatically. To switch to Aliyun instead, change the `url` in `uv.toml` to `https://mirrors.aliyun.com/pypi/simple/`.

## 1. Create and activate the virtual environment

Run from the project root:

```bash
uv venv --python 3.12
```

```bash
source .venv/bin/activate
```

## 2. Clone and install LeRobot

Run from the project root:

```bash
git clone --branch v0.5.1 https://github.com/huggingface/lerobot.git third_party/lerobot
```

Install the editable version with all extras:

```bash
uv pip install -e "./third_party/lerobot[all]"
```

> **Important:** Run this command from the project root, not from inside `third_party/lerobot`. Running it from within the LeRobot directory causes `uv` to use LeRobot's own project environment rather than yours.

## 3. Verify the installation

```bash
python -c "import lerobot; print('lerobot ok')"
```
