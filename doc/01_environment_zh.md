# 环境安装

本项目使用 `uv` 统一管理 Python 环境，Python 版本固定为 `3.12`。LeRobot 通过 `git clone` 下载到 `third_party/lerobot`，并在项目根目录以 editable 模式安装 `lerobot[all]`。

仓库根目录已提供 [`uv.toml`](../uv.toml)，默认优先使用清华 PyPI 镜像加速依赖解析；若清华镜像不可用，`uv` 会继续回退到 PyPI 官方源。若你更想使用阿里云，可将 `url` 改成 `https://mirrors.aliyun.com/pypi/simple/`。

## 1. 创建并激活虚拟环境

在项目根目录执行:

```bash
uv venv --python 3.12
```

```bash
source .venv/bin/activate
```

## 2. 下载并安装 LeRobot

在项目根目录执行:

```bash
git clone https://github.com/huggingface/lerobot.git third_party/lerobot
```

安装 editable 版本的 LeRobot 以及 `all` extras:

```bash
uv pip install -e "./third_party/lerobot[all]"
```

这里的 `uv pip install -e "./third_party/lerobot[all]"` 必须在项目根目录执行，用于安装本地 editable 版 LeRobot，并同时安装 `all` 额外依赖。不要进入 `third_party/lerobot` 后再执行安装，避免 `uv` 使用 LeRobot 仓库自己的项目环境。

## 3. 验证安装

```bash
python -c "import lerobot; print('lerobot ok')"
```
