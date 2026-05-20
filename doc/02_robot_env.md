# Robot Environment Configuration

`robot.env` in the project root centralizes serial port and camera configuration for the robot arms. Recording commands source this file to avoid hard-coding device paths on the command line.

## 1. Identify stable serial port IDs

On Linux, use the stable device paths under `/dev/serial/by-id/` rather than `/dev/ttyUSB*` — the latter can change after a replug.

Before plugging in any arm, note the devices already present:

```bash
ls -l /dev/serial/by-id/
```

If you get `No such file or directory`, no USB serial devices are currently recognized. Confirm the arm is powered and connected via USB, then check for raw serial nodes:

```bash
ls -l /dev/ttyUSB* /dev/ttyACM*
```

If neither appears, the issue is likely the cable, power supply, port, driver, or device enumeration. Inspect the kernel log after plugging in:

```bash
dmesg -w
```

If `/dev/ttyUSB0` appears but `/dev/serial/by-id/` does not, you can use the raw path temporarily — but the number may change on replug. For stable production recording, always prefer `by-id` paths.

Plug in one arm, then run again:

```bash
ls -l /dev/serial/by-id/
```

The newly appeared entry is that arm's stable ID. Output typically looks like:

```
usb-FTDI_USB__-__Serial_Converter_FT8J0ABC-if00-port0 -> ../../ttyUSB0
```

The full path `/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT8J0ABC-if00-port0` is what goes into `robot.env`.

To confirm which `tty` a `by-id` symlink currently resolves to:

```bash
readlink -f /dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT8J0ABC-if00-port0
```

Plug in arms one at a time in this order to avoid confusion:

1. Left follower → record as `LEFT_FOLLOWER_PORT`
2. Right follower → record as `RIGHT_FOLLOWER_PORT`
3. Left leader → record as `LEFT_LEADER_PORT`
4. Right leader → record as `RIGHT_LEADER_PORT`

## 2. Edit `robot.env`

Replace the placeholder paths with your actual device paths:

```bash
export LEFT_FOLLOWER_PORT=/dev/serial/by-id/usb-LEFT_FOLLOWER_ARM_SERIAL
export RIGHT_FOLLOWER_PORT=/dev/serial/by-id/usb-RIGHT_FOLLOWER_ARM_SERIAL
export LEFT_LEADER_PORT=/dev/serial/by-id/usb-LEFT_LEADER_ARM_SERIAL
export RIGHT_LEADER_PORT=/dev/serial/by-id/usb-RIGHT_LEADER_ARM_SERIAL
```

Cameras are configured in the same file. LeRobot's `index_or_path` accepts both integer indices and stable device paths:

```bash
export LEFT_WRIST_CAMERA_INDEX=0
export RIGHT_WRIST_CAMERA_INDEX=1
export FRONT_CAMERA_INDEX=2
```

List available camera devices:

```bash
ls /dev/video*
```

For stable camera paths (recommended):

```bash
ls -l /dev/v4l/by-id/
```

If `by-id` is unavailable, use `by-path`:

```bash
ls -l /dev/v4l/by-path/
```

Example stable camera entries in `robot.env`:

```bash
export LEFT_WRIST_CAMERA_INDEX=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_12345678-video-index0
export RIGHT_WRIST_CAMERA_INDEX=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_87654321-video-index0
export FRONT_CAMERA_INDEX=/dev/v4l/by-path/pci-0000:00:14.0-usb-0:2:1.0-video-index0
```

> **Note:** The same camera may expose both `video-index0` and `video-index1` nodes. Typically `video-index0` is the one that produces frames. Use `lerobot-find-cameras opencv` to confirm.

## 3. Serial port permissions

Accessing `/dev/ttyUSB*` or `/dev/ttyACM*` requires the current user to be in the `dialout` group:

```bash
groups
```

If `dialout` is not listed:

```bash
sudo usermod -aG dialout $USER
```

Log out and back in (or reboot), then verify with `groups` again.

## 4. Load the configuration

Source the file in every new terminal before running any robot command:

```bash
source ./robot.env
```

Verify it loaded correctly:

```bash
echo ${LEFT_FOLLOWER_PORT}
```
