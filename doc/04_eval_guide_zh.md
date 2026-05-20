# 评测操作手册（内部）

本文档面向**评测组**，描述真机评测的完整操作流程。

## 1. 系统架构

```
本机（机械臂）                          本机（选手 Docker）
┌──────────────────────────────┐  gRPC  ┌──────────────────────────┐
│  scripts/start_eval_client.sh│──obs──▶│  选手提供的 policy server  │
│  eval_client.py              │        │  Docker 镜像              │
│  bi_so_follower 双臂          │◀─acts──│  选手自己的模型            │
│  3路摄像头                    │        │  port 8080               │
│  保存前视摄像头 .mp4 视频备份  │        └──────────────────────────┘
└──────────────────────────────┘
```

## 2. 环境准备（一次性）

```bash
source .venv/bin/activate
source ./robot.env

# 确认用户在 dialout 组（串口权限）
groups | grep dialout
# 没有则：sudo usermod -aG dialout $USER，然后重新登录
```

## 3. 评测流程

### 3.1 启动选手 Docker

```bash
sudo docker run --rm -p 8080:8080 <选手镜像名>
# 看到 "Policy server listening on 0.0.0.0:8080" 后继续
```

> 如果报 `address already in use`，查占用进程并杀掉：
> ```bash
> ss -tlnp | grep 8080
> kill -9 <PID>
> ```

### 3.2 启动评测客户端

```bash
cd /home/ubuntu/Desktop/lehome-challenge-real
source .venv/bin/activate
source ./robot.env
export DISPLAY=:0

export TEAM=team_alpha          # 选手队伍标识符
export TASK="Fold the Garment"  # 当前评测任务
export N_EPISODES=2             # 评测 episode 数量
export EPISODE_DURATION=60      # 每 episode 时长（秒）

bash scripts/start_eval_client.sh
```

评测期间：
- 程序在每个 episode 开始前等待 **ENTER 键**，方便操作员重置场景。
- 前视摄像头视频**全程持续录制**，一次评测一个文件。
- Ctrl-C 可随时中断，已录视频正常保存。

### 3.3 验证选手 Docker（不需要真实机械臂）

先用 gRPC 测试脚本确认通信正常，再上真机：

```bash
# 终端 A — 启动选手 Docker
sudo docker run --rm -p 8080:8080 <选手镜像名>

# 终端 B — Stage 1：gRPC 握手
source .venv/bin/activate
python scripts/test_grpc.py --stage=1 --server_addr=localhost:8080

# 终端 B — Stage 2：完整 obs→action 通路（发假观测，验证 action shape=(12,)）
python scripts/test_grpc.py --stage=2 --server_addr=localhost:8080
```

两个 stage 都通过后接真机。

### 3.4 调试时使用 mock server（不需要选手 Docker）

```bash
# 终端 A — 正弦波 mock server，机械臂会动
source .venv/bin/activate
python scripts/mock_policy_server.py --port=8080 --demo --amplitude=10 --period=6

# 终端 B — 评测客户端（接真实机械臂）
source ./robot.env
export DISPLAY=:0
TEAM=test_run bash scripts/start_eval_client.sh
```

不带 `--demo` 则保持位置（hold position），适合验证通路而不动机械臂。

## 4. 数据存储格式

```
Datasets/eval/
└── <team>/
    └── <task_slug>/
        └── <task_slug>_<team>_<YYYYMMDD_HHMMSS>.mp4
```

评测期间全程录制前视（头部）摄像头视频，从第一个 episode 开始到评测结束（或 Ctrl-C）。每次评测生成一个 MP4 文件。

## 5. 评测参数速查

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `TEAM` | **必填** | 队伍标识符（影响文件名） |
| `SERVER_ADDR` | `localhost:8080` | 选手服务端地址 |
| `TASK` | `Fold the Garment` | 任务描述 |
| `N_EPISODES` | `5` | 评测 episode 数 |
| `EPISODE_DURATION` | `60` | 每 episode 时长（秒）|
| `FPS` | `20` | 控制频率 |
| `ACTIONS_PER_CHUNK` | `20` | 每次服务端调用返回的动作数 |

## 6. 常见问题

**端口占用 `address already in use`**  
→ `ss -tlnp | grep 8080` 找到 PID，`kill -9 <PID>` 后重启 Docker。

**连接失败 `UNAVAILABLE`**  
→ 确认 Docker 日志出现 `listening on 0.0.0.0:8080`；检查 `-p 8080:8080` 映射。

**机械臂未动作**  
→ 服务端日志确认 `GetActions` 有输出；`GetActions` 超时 5 秒返回空，机械臂暂停。先用 `test_grpc.py --stage=2` 验证通路。

**视频文件为空或损坏**  
→ 确认 `source ./robot.env` 已执行；Orbbec 前视摄像头需要 `warmup_s: 5` 预热约 2.5 秒。

**动作全部静止（hold position）**  
→ 这是模板 `server.py` 的默认行为（保持位置安全占位），选手换成真实模型后会有动作。
   调试时改用 `mock_policy_server.py --demo` 查看实际运动。
