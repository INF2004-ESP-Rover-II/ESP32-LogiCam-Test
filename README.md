# ESP32-LogiCam-Test

An ESP32-S3 acting as a USB host for a Logitech UVC webcam (plugged into the
board's USB-OTG port), streaming MJPEG video over Wi-Fi, with a Python-side
ArUco marker detection pipeline reading that stream.

This replaces an earlier attempt using the ESP32's built-in camera module
(ESP32-CAM / OV5640), which had persistent focus/blur issues that prevented
reliable marker detection. Routing a real USB webcam through the board's
USB-OTG port gives much sharper images.

## Why ESP-IDF instead of the Arduino IDE?

The Arduino ESP32 board package only exposes the built-in camera peripheral
(`esp_camera.h`) and Wi-Fi/HTTP libraries - it has no USB Host stack at all.
Getting the ESP32-S3 to act as a USB host (enumerating and reading frames
from an external USB webcam, instead of the more common USB *device* mode)
requires Espressif's USB Host Library and the `usb_stream` component, both
of which only exist in the full ESP-IDF SDK. There is no Arduino wrapper for
this, so this part of the project had to move to raw ESP-IDF with its own
build system (`idf.py`) and project layout.

## Repo layout

```
firmware/       ESP-IDF project (C) - runs on the ESP32-S3
software/       Python scripts - run on your computer
```

### firmware/

ESP-IDF project targeting `esp32s3`. Key files:

- `main/app_main.c` - Wi-Fi connection, USB host / UVC webcam init via
  `usb_stream`, and an HTTP server serving `/stream` (MJPEG) and `/capture`
  (single JPEG).
- `sdkconfig.defaults` - includes `CONFIG_CTRL_TRANSFER_DATA_MAX_BYTES=2048`,
  which is **required** - see Troubleshooting below.
- `dependencies.lock` - pins the exact `usb_stream` version (1.5.2) that is
  confirmed working. Do not delete this file.

### software/

- **`esp32_aruco_stream.py`** - Main entry point. Connects to the ESP32's
  MJPEG stream and runs live ArUco detection using the class below. Run
  this for normal operation.
- **`challenge1_aruco_detector.py`** - Core detector class
  (`ArucoMarkerDetector`): marker detection, overlay drawing, and landing
  zone classification. Imported by the script above; not meant to be run
  directly.
- **`debug_aruco.py`** - Diagnostic tool for troubleshooting detection
  issues against the ESP32 stream. Shows a live "Rejected" marker count,
  which helps tell apart blur/focus problems (many rejected, zero detected)
  from a dictionary mismatch. Use this first if detection stops working.
- **`debug_aruco_local_webcam.py`** - Same diagnostic tool, pointed at your
  computer's local webcam instead of the ESP32 stream. Use this to check
  whether a problem is caused by the ESP32/stream specifically, or by the
  detection code/settings themselves.
- **`dict_finder.py`** - One-off utility. Tests a saved debug frame
  (`debug_gray_*.jpg` from `debug_aruco.py`) against every standard
  ArUco/AprilTag dictionary OpenCV ships and reports which one actually
  decodes your markers. Use this if you switch to a different marker set.

## Prerequisites

- **ESP-IDF v5.2.7** specifically - not the latest v6.x release. ESP-IDF 6.x
  externalized the `usb` component in a way that breaks `usb_stream`'s
  CMake config, and even the workaround (the separate `espressif/usb`
  managed component) requires IDF >=5.4/5.5. v5.2.7 is genuinely the
  version confirmed working here. Install it via the ESP-IDF Installation
  Manager app, or manually.
- Python 3 with `opencv-contrib-python` (not plain `opencv-python` - it
  needs the `cv2.aruco` module) and `numpy`.
- A Logitech (or other UVC-class) USB webcam, and a USB-C-male-to-USB-A-
  female adapter to plug it into the ESP32-S3's USB-OTG port.

## Firmware: build & flash

1. Open the `firmware/` folder (not the repo root) in VS Code with the
   ESP-IDF extension installed - it needs to see `CMakeLists.txt` and
   `main/` at the workspace root.
2. Make sure your terminal/VS Code is using ESP-IDF v5.2.7. If activating
   manually in a terminal, prefer:
   ```
   . /path/to/.espressif/v5.2.7/esp-idf/export.sh
   ```
   over the ESP-IDF Installation Manager's `activate_idf_v5.2.7.sh` script -
   on at least one machine that script resolved the wrong compiler toolchain
   version even after a fresh terminal and reinstalling tools.
3. Set the target (only needed on a fresh clone, since the generated
   `sdkconfig` isn't committed - `sdkconfig.defaults` already has the
   required fix baked in):
   ```
   idf.py set-target esp32s3
   ```
4. Build and flash (via the ESP-IDF Explorer panel in VS Code, or the
   terminal):
   ```
   idf.py -p <your-serial-port> flash monitor
   ```
   If it fails to connect, put the board in download mode manually: hold
   **BOOT**, tap **RESET**, keep holding BOOT for ~2 seconds, then release,
   and retry the flash command immediately.
5. **Wi-Fi credentials are currently hardcoded** in `main/app_main.c`
   (`WIFI_SSID` / `WIFI_PASSWORD`, near the top of the file) - update them
   there before flashing if you're on a different network.
   > ⚠️ These are committed in plaintext in this repo's history. Don't rely
   > on this for anything beyond local testing, and rotate the password if
   > this repo is ever made public.

### Hardware wiring

Plug the USB webcam directly into the ESP32-S3's **USB-OTG** port (not the
USB-UART port used for flashing/serial monitor). Avoid hubs/extra adapters
in that chain if possible - USB host mode on this board is already tight on
enumeration and bus power.

## Software: running detection

```
cd software
python3 esp32_aruco_stream.py
```

Update `ESP32_IP` at the top of the script to match whatever IP address the
serial monitor prints after the board connects to Wi-Fi. Press `q` to quit,
`s` to save a snapshot + landing-zone classification JSON.

If detection isn't working, run `debug_aruco.py` first to see the live
"Rejected" count and figure out whether it's a focus/lighting issue or a
dictionary mismatch.

## Troubleshooting

- **`Tool doesn't match supported version` during `idf.py set-target`**:
  wrong compiler toolchain on PATH. Use `export.sh` instead of the
  Installation Manager's activate script (see step 2 above).
- **`Failed to resolve component 'usb'` / usb_stream build errors**: you're
  likely on ESP-IDF v6.x. Switch to v5.2.7.
- **`Configuration descriptor larger than control transfer max length`**
  during USB enumeration: `CONFIG_CTRL_TRANSFER_DATA_MAX_BYTES` is too
  small for this webcam's combined UVC+UAC descriptor. It's already set to
  `2048` (the max this component allows) in `sdkconfig.defaults` - if you
  changed it, put it back.
- **Port busy / `Resource busy` when flashing**: something else (VS Code's
  monitor pane, a leftover terminal) still has the serial port open. Find
  it with `lsof <port>` and `kill` the PID.
- **Python script times out connecting to `/stream` but a browser can view
  it fine**: the ESP32's HTTP server only supports a handful of concurrent
  connections. Close any browser tab that has the stream open before
  running the Python script.
- **Markers detected as shapes (high "Rejected" count) but never decoded**:
  dictionary mismatch, not a focus problem. Run `dict_finder.py` against a
  saved `debug_gray_*.jpg` to find the correct dictionary, then update
  `ARUCO_DICT_TYPE` / `ARUCO_DICT` in the relevant script(s).
