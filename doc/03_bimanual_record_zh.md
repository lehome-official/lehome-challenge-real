# 双臂数据采集

本节使用 LeRobot 的双臂类型采集数据:

- `--robot.type=bi_so_follower`
- `--teleop.type=bi_so_leader`

执行录制前，先完成 [环境安装](01_environment.md) 和 [机械臂环境变量配置](02_robot_env.md)。

## 每次采集前需要确认的参数

每次开始采集前，优先确认下面这些值:

- `DATASET_NAME`: 本次数据集名称，会用于 `Datasets` 下的保存目录和 Hugging Face repo 名称。
- `--dataset.single_task`: 本次采集任务描述，需要和实际任务保持一致。
- `--dataset.num_episodes`: 本次要采集的 episode 数量。
- `HF_USER`: Hugging Face 用户名。本地采集默认使用 `local` 占位，保证 `repo_id` 格式正确。
- `robot.env`: 四个机械臂串口和三个相机编号或固定路径是否对应当前设备。

通常每次采集只需要改 `DATASET_NAME`、`--dataset.single_task` 和 `--dataset.num_episodes`。只有更换 USB 口、机械臂或摄像头时，才需要重新检查 `robot.env`。

如果录制命令提示当前用户不在 `dialout` 组，先执行:

```bash
sudo usermod -aG dialout $USER
```

然后退出当前登录会话并重新登录，或者重启电脑。重新登录后再执行下面的手动录制命令。

## 手动录制命令

在项目根目录执行:

```bash
source .venv/bin/activate
source ./robot.env

# 四类衣服：top_long | top_short | pant_long | pant_short
GARMENT=top_long
N=1_1
DATASET_NAME=${GARMENT}_${N}
DATASET_ROOT=./Datasets/${DATASET_NAME}
HF_USER=local

lerobot-record \
    --robot.type=bi_so_follower \
    --robot.left_arm_config.port=${LEFT_FOLLOWER_PORT} \
    --robot.right_arm_config.port=${RIGHT_FOLLOWER_PORT} \
    --robot.id=bimanual_follower \
    --robot.left_arm_config.cameras="{ wrist: {type: opencv, index_or_path: ${LEFT_WRIST_CAMERA_INDEX}, width: ${LEFT_WRIST_CAMERA_WIDTH}, height: ${LEFT_WRIST_CAMERA_HEIGHT}, fps: ${LEFT_WRIST_CAMERA_FPS}}}" \
    --robot.right_arm_config.cameras="{ wrist: {type: opencv, index_or_path: ${RIGHT_WRIST_CAMERA_INDEX}, width: ${RIGHT_WRIST_CAMERA_WIDTH}, height: ${RIGHT_WRIST_CAMERA_HEIGHT}, fps: ${RIGHT_WRIST_CAMERA_FPS}}, front: {type: opencv, index_or_path: ${FRONT_CAMERA_INDEX}, width: ${FRONT_CAMERA_WIDTH}, height: ${FRONT_CAMERA_HEIGHT}, fps: ${FRONT_CAMERA_FPS}, backend: V4L2, fourcc: MJPG, warmup_s: 5}}" \
    --teleop.type=bi_so_leader \
    --teleop.left_arm_config.port=${LEFT_LEADER_PORT} \
    --teleop.right_arm_config.port=${RIGHT_LEADER_PORT} \
    --teleop.id=bimanual_leader \
    --display_data=true \
    --dataset.root=${DATASET_ROOT} \
    --dataset.repo_id=${HF_USER}/${DATASET_NAME} \
    --dataset.num_episodes=25 \
    --dataset.fps=20 \
    --dataset.single_task="Fold the Garment" \
    --dataset.streaming_encoding=true \
    --dataset.encoder_threads=1 \
    --dataset.push_to_hub=false 
```

## 参数说明

- `LEFT_FOLLOWER_PORT` / `RIGHT_FOLLOWER_PORT`: 左右 follower 机械臂串口。
- `LEFT_LEADER_PORT` / `RIGHT_LEADER_PORT`: 左右 leader 机械臂串口。
- `LEFT_WRIST_CAMERA_INDEX` / `RIGHT_WRIST_CAMERA_INDEX`: 左右腕部相机编号或 `/dev/v4l/...` 固定路径。
- `FRONT_CAMERA_INDEX`: 前视相机编号或 `/dev/v4l/...` 固定路径。
- `LEFT_WRIST_CAMERA_WIDTH` / `LEFT_WRIST_CAMERA_HEIGHT` / `LEFT_WRIST_CAMERA_FPS`: 左腕相机采集模式。
- `RIGHT_WRIST_CAMERA_WIDTH` / `RIGHT_WRIST_CAMERA_HEIGHT` / `RIGHT_WRIST_CAMERA_FPS`: 右腕相机采集模式。
- `FRONT_CAMERA_WIDTH` / `FRONT_CAMERA_HEIGHT` / `FRONT_CAMERA_FPS`: 前视相机采集模式。
- `DATASET_ROOT`: 本次采集数据保存到本地 `Datasets` 下的新目录。
- `HF_USER`: Hugging Face 用户名或本地占位名，用于生成数据集 repo id。
- `--dataset.push_to_hub=false`: 本地保存数据，不上传 Hugging Face Hub。

`--dataset.root=${DATASET_ROOT}` 用于指定本地保存路径。不要直接写成 `--dataset.root=./Datasets`，因为 LeRobot 会创建 `root` 目录，目标目录已存在时会报错。

如果日志里看到 `root: ''` 或 `repo_id: '/'`，说明 `DATASET_ROOT`、`HF_USER` 或 `DATASET_NAME` 没有在当前终端设置，需要重新从上面的完整命令开始执行。

如果日志里看到 `Specifying 'width' is required for the camera to be used in a robot`，说明相机配置里缺少 `width`、`height` 或 `fps`，需要确认已经 `source ./robot.env`，并且上面的录制命令包含这些相机参数。

如果日志里看到 `failed to set capture_width=640 (actual_width=1024)`，说明对应相机不接受当前配置的分辨率。先确认 `robot.env` 里的相机编号是否对应正确设备；如果编号正确，就把该相机的 `*_CAMERA_WIDTH`、`*_CAMERA_HEIGHT`、`*_CAMERA_FPS` 改成它实际支持的模式。


相机好像出了点问题 可以直接插ba吗
left wrist