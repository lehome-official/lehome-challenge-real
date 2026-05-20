# Bimanual Data Collection

This section covers data collection using LeRobot's bimanual robot types:

- `--robot.type=bi_so_follower`
- `--teleop.type=bi_so_leader`

Complete [Environment Setup](01_environment.md) and [Robot Environment Configuration](02_robot_env.md) before proceeding.

## Parameters to confirm before each session

- **`DATASET_NAME`** — Name of this recording session. Used as the local save directory under `Datasets/` and as the Hugging Face repo name.
- **`--dataset.single_task`** — Task description for this session. Must match the actual task being performed.
- **`--dataset.num_episodes`** — Number of episodes to record this session.
- **`HF_USER`** — Hugging Face username. Use `local` as a placeholder for local-only recording (keeps `repo_id` format valid).
- **`robot.env`** — Confirm all four arm serial ports and three camera entries match the current physical setup.

Typically only `DATASET_NAME`, `--dataset.single_task`, and `--dataset.num_episodes` need to change between sessions. Re-check `robot.env` only after swapping USB ports, arms, or cameras.

If the recording command reports the current user is not in the `dialout` group, run:

```bash
sudo usermod -aG dialout $USER
```

Then log out and back in before retrying.

## Recording command

Run from the project root:

```bash
source .venv/bin/activate
source ./robot.env
export DISPLAY=:0   # required for pynput keyboard capture under Wayland

# Garment types: top_long | top_short | pant_long | pant_short
GARMENT=top_long
N=$(printf "%03d" $(( $(ls -d ./Datasets/${GARMENT}_* 2>/dev/null | wc -l) + 1 )))
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

## Parameter reference

| Variable | Description |
|----------|-------------|
| `LEFT_FOLLOWER_PORT` / `RIGHT_FOLLOWER_PORT` | Serial ports for the left and right follower arms |
| `LEFT_LEADER_PORT` / `RIGHT_LEADER_PORT` | Serial ports for the left and right leader arms |
| `LEFT_WRIST_CAMERA_INDEX` / `RIGHT_WRIST_CAMERA_INDEX` | Index or `/dev/v4l/...` path for the wrist cameras |
| `FRONT_CAMERA_INDEX` | Index or `/dev/v4l/...` path for the front camera |
| `*_CAMERA_WIDTH` / `*_CAMERA_HEIGHT` / `*_CAMERA_FPS` | Capture resolution and frame rate per camera |
| `DATASET_ROOT` | Local save path — a new subdirectory per session under `Datasets/` |
| `HF_USER` | Hugging Face username or `local` placeholder |
| `--dataset.push_to_hub=false` | Save locally; do not upload to Hugging Face Hub |

> Set `--dataset.root=${DATASET_ROOT}` to a new subdirectory each time. Do not pass `--dataset.root=./Datasets` directly — LeRobot will error if the target directory already exists.

## Common errors

**`root: ''` or `repo_id: '/'`**
`DATASET_ROOT`, `HF_USER`, or `DATASET_NAME` is not set in the current terminal. Re-run the full block above starting from `source .venv/bin/activate`.

**`Specifying 'width' is required for the camera to be used in a robot`**
Camera config is missing `width`, `height`, or `fps`. Confirm `source ./robot.env` has been run and that the recording command includes all camera dimension variables.

**`failed to set capture_width=640 (actual_width=1024)`**
The camera does not support the configured resolution. Verify the camera index in `robot.env` points to the correct device; if correct, update `*_CAMERA_WIDTH`, `*_CAMERA_HEIGHT`, `*_CAMERA_FPS` to a resolution the camera actually supports.

**`TimeoutError: Timed out waiting for frame from camera … after 1000 ms`**
The Orbbec front camera needs ~2.5 s to deliver its first frame. Add `warmup_s: 5` to the front camera config (already included in the command above).
