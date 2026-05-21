# 比赛现场评测手册（裁判/组委会）

本文档是真机评测的完整操作手册。在新机器上从头到尾按照本文操作，无需查看其他文档即可完成所有配置并开始评测。

---

## 0. 开赛前检查清单

比赛开始前确认以下所有项：

- [ ] Docker 已安装：`docker --version`
- [ ] Python 3.12 环境已配置（§1.1）
- [ ] `robot.env` 已填写正确的设备路径（§1.2）
- [ ] 当前用户在 `dialout` 组（§1.3）
- [ ] mock server 硬件测试已通过（§1.4）
- [ ] `DISPLAY=:0` 已设置（键盘监听在硬件测试时可正常使用）

---

## 1. 机器一次性初始化配置

在新机器上执行一次，之后不需要重复。

### 1.1 克隆仓库并安装环境

```bash
git clone <仓库地址> lehome-challenge-real
cd lehome-challenge-real

# 创建 Python 3.12 虚拟环境
uv venv --python 3.12
source .venv/bin/activate

# 安装 LeRobot（含全部扩展依赖）
uv pip install -e "./third_party/lerobot[all]"
```

> 如果没有 `uv`：`pip install uv`
>
> 如果 `third_party/lerobot` 为空：
> ```bash
> git clone https://github.com/huggingface/lerobot.git third_party/lerobot
> uv pip install -e "./third_party/lerobot[all]"
> ```

验证安装：
```bash
python -c "import lerobot; print('lerobot ok')"
```

### 1.2 配置硬件端口和摄像头

```bash
cp robot.env.template robot.env
nano robot.env   # 填写实际设备路径
```

依次插入每条机械臂，查找稳定的串口路径：
```bash
ls -l /dev/serial/by-id/
```

在 `robot.env` 中填写实际路径：
```bash
export LEFT_FOLLOWER_PORT=/dev/serial/by-id/usb-左臂从动...
export RIGHT_FOLLOWER_PORT=/dev/serial/by-id/usb-右臂从动...
export LEFT_WRIST_CAMERA_INDEX=0    # 或 /dev/v4l/by-id/...
export RIGHT_WRIST_CAMERA_INDEX=1
export FRONT_CAMERA_INDEX=2
# 分辨率和帧率模板默认值已填好，无需修改
```

详细说明参见 [02_robot_env.md](02_robot_env.md)。

### 1.3 串口权限

```bash
groups | grep dialout
```

如果没有 `dialout`：
```bash
sudo usermod -aG dialout $USER
```

**必须注销重新登录（或重启）**，然后用 `groups` 确认。

### 1.4 用 mock server 验证硬件（必做）

此步骤确认机械臂能正确响应指令，且评测流程完整可用，**在接入任何选手 Docker 之前完成**。

**终端 A — 启动 mock server（保持位置，机械臂不动）：**
```bash
source .venv/bin/activate
python scripts/mock_policy_server.py --port=8080
```

**终端 B — 启动评测客户端：**
```bash
cd lehome-challenge-real
source .venv/bin/activate
source ./robot.env
export DISPLAY=:0

TEAM=hardware_test N_EPISODES=1 EPISODE_DURATION=10 \
bash scripts/start_eval_client.sh
```

终端 B 的预期输出：
```
===========================================================
  Episode 1/1   task: Fold the Garment
  Keys:  →/d finish    ←/a redo    ESC stop all
===========================================================
  Reset the scene, then press ENTER to start ...
```

按下 ENTER 后，确认：
- 步骤日志持续打印
- 机械臂保持当前姿态不动（mock server 默认 hold position）
- 键盘响应：按 `→` 可提前结束 episode
- `Datasets/eval/hardware_test/` 目录下生成了视频文件

**可选：用正弦波 demo 验证机械臂实际运动（机械臂会动）：**
```bash
# 将终端 A 的 mock server 替换为 demo 版本：
python scripts/mock_policy_server.py --port=8080 --demo --amplitude=5 --period=6
```

运行 `--demo` 前确认机械臂周围没有障碍物。

---

## 2. 每位选手的评测流程

每位选手重复以下步骤。配置约需 5 分钟，加上实际评测时间。

### 2.1 加载选手的 Docker 镜像

选手提交 `.tar.gz` 文件，加载方式：

```bash
docker load < lehome-policy-teamname.tar.gz
```

输出会显示镜像名称：
```
Loaded image: lehome-policy-teamname:latest
```

如果名称不清晰，执行 `docker images` 查看最新加载的镜像。

> **GPU 选手：** 如选手注明需要 GPU，在 2.3 步骤中使用 `--gpus all`。

### 2.2 验证 Docker 通信（不需要真实机械臂，30 秒）

先用假观测验证 gRPC 协议是否正常，再接入真机。

```bash
# 终端 A — 启动选手 Docker：
docker run --rm -p 8080:8080 lehome-policy-teamname
# 等到看到："Policy server listening on 0.0.0.0:8080"

# 终端 B — 运行冒烟测试：
source .venv/bin/activate
python docker/policy_server/test_client.py \
    --server_addr=localhost:8080 --stage=2 --n_steps=3
```

预期结果：
```
  Stage 1 — Handshake            : PASS ✓
  Stage 2 — obs→action loop      : PASS ✓
  RESULT: ALL TESTS PASSED
```

**如果任一 stage 失败，不要连接真实机械臂。** 将错误信息反馈给选手调试。

### 2.3 启动评测会话

先停止 2.2 中终端 A 的 Docker（`Ctrl-C`），然后：

```bash
# 终端 A — 重新启动 Docker（有 GPU 需求时加 --gpus all）：
docker run --rm -p 8080:8080 lehome-policy-teamname
# GPU 版本：
# docker run --rm --gpus all -p 8080:8080 lehome-policy-teamname

# 等到看到："Policy server listening on 0.0.0.0:8080"
```

```bash
# 终端 B — 启动评测：
cd lehome-challenge-real
source .venv/bin/activate
source ./robot.env
export DISPLAY=:0

export TEAM=teamname           # 选手标识（用于文件名）
export TASK="Fold the Garment"
export N_EPISODES=5            # 评测 episode 数量
export EPISODE_DURATION=60     # 每 episode 最长时间（秒）

bash scripts/start_eval_client.sh
```

### 2.4 评测中的键盘控制

| 按键 | 何时按 | 效果 |
|------|--------|------|
| `→` 或 `d` | 任务完成 / 机械臂失败 / 想提前结束 | 本轮结束，计入成绩，进入下一轮 |
| `←` 或 `a` | 场景未摆好 / 机械臂初始位置不对 / 误操作 | 本轮**不计入**，重复同一轮编号 |
| `ESC` | 紧急情况，需要立即停止 | 整个会话结束，视频已保存 |
| `ENTER`（在提示符处） | 场景已重置，准备好开始 | 启动下一个 episode |

键盘事件在每个单独动作之间检查（≤50 ms 响应），按键后最多 50ms 机械臂停止执行。

### 2.5 Episode 流程说明

```
===========================================================
  Episode 1/5   task: Fold the Garment
  Max duration: 60 s
  Keys:  →/d finish    ←/a redo    ESC stop all
===========================================================
  Reset the scene, then press ENTER to start ...
```

1. **物理重置**场景（摆放好衣物，将机械臂归位）。
2. 按 **ENTER** — 机械臂开始运动。
3. 观察 episode 执行：
   - 有效结果（任务完成或超时）：按 `→` 结束，或等待超时 → 计为第 N 轮，进入下一轮。
   - 无效（场景未准备好、碰撞、操作失误）：按 `←` → 本轮作废，重复同一轮编号。
4. 重复直到所有 `N_EPISODES` 完成。

### 2.6 评测结束后

```bash
# 查看录制的视频文件：
ls Datasets/eval/<teamname>/fold_the_garment/

# 停止选手 Docker（终端 A）：
Ctrl-C
```

视频文件命名格式：`fold_the_garment_<team>_<YYYYMMDD_HHMMSS>.mp4`

---

## 3. 常用命令速查

```bash
# 在每个新终端中首先执行（必须）
source .venv/bin/activate && source ./robot.env && export DISPLAY=:0

# 加载选手 Docker
docker load < lehome-policy-teamname.tar.gz

# 启动 Docker
docker run --rm -p 8080:8080 lehome-policy-teamname
# GPU 版：docker run --rm --gpus all -p 8080:8080 lehome-policy-teamname

# 验证 Docker 通信（无需真机，30 秒）
python docker/policy_server/test_client.py --server_addr=localhost:8080 --stage=2

# 启动评测
TEAM=teamname N_EPISODES=5 EPISODE_DURATION=60 bash scripts/start_eval_client.sh

# 硬件验证：mock server 保持位置
python scripts/mock_policy_server.py --port=8080

# 硬件验证：正弦波 demo（机械臂会动）
python scripts/mock_policy_server.py --port=8080 --demo --amplitude=5 --period=6

# 释放占用 8080 端口的进程
ss -tlnp | grep 8080   # 查找 PID
kill -9 <PID>
```

---

## 4. 环境变量参数说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TEAM` | **必填** | 选手队伍标识（影响视频文件名） |
| `TASK` | `Fold the Garment` | 任务描述，传给 policy server |
| `N_EPISODES` | `2` | 评测 episode 总数 |
| `EPISODE_DURATION` | `60` | 每 episode 最长时间（秒） |
| `SERVER_ADDR` | `localhost:8080` | policy Docker 地址 |
| `FPS` | `20` | 控制频率 — 必须与训练数据采样率一致 |
| `ACTIONS_PER_CHUNK` | `20` | 每次 gRPC 调用返回的动作数 — 必须与模型 chunk_size 一致 |

`FPS` 和 `ACTIONS_PER_CHUNK` 需与选手训练时的设置一致。如有疑问询问选手。默认值（20 / 20）适用于大多数以 20Hz 训练的 LeRobot ACT 模型。

---

## 5. 常见问题处理

### 8080 端口被占用
```bash
ss -tlnp | grep 8080   # 找到 PID
kill -9 <PID>
```
然后重启 Docker。

### Docker 启动很慢，迟迟不出现 "listening"
模型 checkpoint 较大，加载需要时间。等待最多 2 分钟。如仍未出现，去掉 `--rm` 保留容器日志：
```bash
docker run -p 8080:8080 lehome-policy-teamname
docker logs <container-id>
```

### test_client 阶段 2 失败（action shape 或 dtype 错误）
选手的 `_predict()` 返回了错误形状或类型的 tensor，将错误信息反馈给选手。**不要连接真实机械臂。**

### eval_client 报 "LEFT_FOLLOWER_PORT not set"
```bash
source ./robot.env   # 必须在运行 start_eval_client.sh 的同一终端中执行
```

### eval_client 报 "LeRobot not found" 或 ImportError
```bash
source .venv/bin/activate   # 必须先激活虚拟环境
```

### 键盘按键无响应
`pynput` 需要 display 环境。确认设置了：
```bash
export DISPLAY=:0
```
如果通过 SSH 连接，请使用 `ssh -X` 或连接物理显示器。

### 机械臂完全不动（全程保持静止）
这是选手 `server.py` 模板的**默认行为**（保持位置，安全占位），选手未替换 `_predict()` 中的真实模型时就会如此。确认加载的是正确的 Docker 镜像。

### 机械臂动作卡顿或中途停止
模型推理耗时超过 200ms 或 5s 超时限制。请选手在 `__init__` 中添加 warm-up forward pass，确认推理延迟。

### 前视摄像头录制的视频前几帧是黑屏
Orbbec 前视摄像头预热需约 5 秒，前几帧黑屏属于正常现象。`warmup_s: 5` 已在机器人配置中设置。

### 视频文件时长与 episode 实际时长不符
确认 `ACTIONS_PER_CHUNK` 与选手模型每次返回的动作数一致（默认 20）。如选手使用不同的 chunk_size，需相应调整此参数后重新运行。
