# 机械臂环境变量配置

项目根目录的 `robot.env` 用于集中配置机械臂串口和相机编号。手动录制命令会先 `source ./robot.env`，避免把设备路径直接写在命令里。

## 1. 查看固定串口号

Linux 下建议使用 `/dev/serial/by-id/` 里的稳定设备路径。机械臂重新插拔后，`/dev/ttyUSB0` 这类编号可能变化，但 `/dev/serial/by-id/` 通常保持稳定。

先不要插入目标机械臂，记录当前已有设备:

```bash
ls -l /dev/serial/by-id/
```

如果这里提示 `No such file or directory`，说明系统当前没有识别到任何 USB 串口设备，或者还没有创建稳定的 `by-id` 链接。先确认机械臂已经通电并通过 USB 连接到电脑，然后检查是否出现原始串口设备:

```bash
ls -l /dev/ttyUSB* /dev/ttyACM*
```

如果也没有 `/dev/ttyUSB*` 或 `/dev/ttyACM*`，通常是 USB 线、供电、接口、驱动或设备没有枚举的问题。插拔机械臂后可以查看内核日志:

```bash
dmesg -w
```

如果出现了 `/dev/ttyUSB0` 或 `/dev/ttyACM0`，但没有 `/dev/serial/by-id/`，可以临时使用对应的 `/dev/ttyUSB*` 或 `/dev/ttyACM*` 路径继续调试；不过这些编号在重新插拔后可能变化，正式录制前仍建议使用 `/dev/serial/by-id/` 中的稳定路径。

插入一个机械臂后，再执行一次:

```bash
ls -l /dev/serial/by-id/
```

新出现的那一行就是这个机械臂的固定 ID。输出通常类似:

```bash
usb-FTDI_USB__-__Serial_Converter_FT8J0ABC-if00-port0 -> ../../ttyUSB0
```

其中 `/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT8J0ABC-if00-port0` 就是应该写进 `robot.env` 的稳定路径。

如果想确认这个固定 ID 当前对应哪个 tty 设备，可以执行:

```bash
readlink -f /dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT8J0ABC-if00-port0
```

建议按下面顺序逐个插入并记录，避免混淆:

1. 插入左 follower，记录为 `LEFT_FOLLOWER_PORT`
2. 插入右 follower，记录为 `RIGHT_FOLLOWER_PORT`
3. 插入左 leader，记录为 `LEFT_LEADER_PORT`
4. 插入右 leader，记录为 `RIGHT_LEADER_PORT`

## 2. 修改 `robot.env`

把 `robot.env` 中的占位路径替换为真实设备路径:

```bash
export LEFT_FOLLOWER_PORT=/dev/serial/by-id/usb-LEFT_FOLLOWER_ARM_SERIAL
export RIGHT_FOLLOWER_PORT=/dev/serial/by-id/usb-RIGHT_FOLLOWER_ARM_SERIAL
export LEFT_LEADER_PORT=/dev/serial/by-id/usb-LEFT_LEADER_ARM_SERIAL
export RIGHT_LEADER_PORT=/dev/serial/by-id/usb-RIGHT_LEADER_ARM_SERIAL
```

相机也在同一个文件中配置。LeRobot 的 `index_or_path` 支持数字编号，也支持固定设备路径，所以这些变量既可以写成 `0`、`1`、`2`，也可以写成 `/dev/v4l/by-id/...` 或 `/dev/v4l/by-path/...`:

```bash
export LEFT_WRIST_CAMERA_INDEX=0
export RIGHT_WRIST_CAMERA_INDEX=1
export FRONT_CAMERA_INDEX=2
```

可用下面的命令查看摄像头设备:

```bash
ls /dev/video*
```

如果想像机械臂串口一样固定相机，优先查看:

```bash
ls -l /dev/v4l/by-id/
```

如果没有 `by-id`，再查看:

```bash
ls -l /dev/v4l/by-path/
```

把对应相机的稳定路径写进 `robot.env`，例如:

```bash
export LEFT_WRIST_CAMERA_INDEX=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_12345678-video-index0
export RIGHT_WRIST_CAMERA_INDEX=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_87654321-video-index0
export FRONT_CAMERA_INDEX=/dev/v4l/by-path/pci-0000:00:14.0-usb-0:2:1.0-video-index0
```

注意同一个摄像头可能会出现 `video-index0` 和 `video-index1` 两个节点。通常选择能正常出图的 `video-index0`，也可以用 `lerobot-find-cameras opencv` 辅助确认。

## 3. 串口权限

Linux 下访问 `/dev/ttyUSB*` 或 `/dev/ttyACM*` 通常需要当前用户属于 `dialout` 组。检查当前用户组:

```bash
groups
```

如果输出中没有 `dialout`，执行:

```bash
sudo usermod -aG dialout $USER
```

然后退出当前登录会话并重新登录，或者重启电脑。重新登录后再执行 `groups`，确认包含 `dialout`。

## 4. 加载配置

每次打开新终端后，都需要在项目根目录重新加载一次:

```bash
source ./robot.env
```

检查配置是否生效:

```bash
echo ${LEFT_FOLLOWER_PORT}
```
