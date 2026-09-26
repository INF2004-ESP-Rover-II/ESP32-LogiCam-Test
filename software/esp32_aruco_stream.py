#!/usr/bin/env python3
"""
Aruco marker detection using the ESP32-S3 camera's MJPEG stream instead of
a USB webcam.

Uses ArucoMarkerDetector from challenge1_aruco_detector.py, unchanged - the
only difference from your original scripts is the video SOURCE: instead of
cv2.VideoCapture(0) (a local USB webcam), we point OpenCV at the ESP32's
stream URL over Wi-Fi.

Setup:
    1. Make sure esp32_s3_camera_web.ino is uploaded and running, and you've
       confirmed via Serial Monitor it printed something like:
           MJPEG stream available at: http://192.168.1.42:81/stream
    2. Put that exact IP address into ESP32_IP below.
    3. Run: python3 esp32_aruco_stream.py
    4. Press 'q' to quit, 's' to save the current frame + detection JSON.

Requires: opencv-python (opencv-contrib-python for the aruco module),
          numpy
"""

import cv2
import json
import time
from challenge1_aruco_detector import ArucoMarkerDetector

# ---------------------------------------------------------------------
# Fill in the IP address printed by the ESP32 over serial
# ---------------------------------------------------------------------
ESP32_IP = "172.20.10.5"
STREAM_URL = f"http://{ESP32_IP}/stream"

# Match this to whichever dictionary your printed/displayed markers use.
# challenge1_aruco_detector.py defaults to DICT_6X6_250; debug_aruco.py used
# DICT_4X4_250. Change this if your markers don't detect.
ARUCO_DICT = cv2.aruco.DICT_6X6_250


def main():
    detector = ArucoMarkerDetector(aruco_dict_type=ARUCO_DICT)

    print(f"Connecting to ESP32 stream at {STREAM_URL} ...")
    cap = cv2.VideoCapture(STREAM_URL)

    if not cap.isOpened():
        print("Could not open the stream. Check that:")
        print("  - The ESP32 is powered on and connected to Wi-Fi")
        print("  - ESP32_IP above matches what the Serial Monitor printed")
        print("  - Your computer is on the same Wi-Fi network as the ESP32")
        return

    print("Connected! Press 'q' to quit, 's' to save frame + detections.")
    frame_count = 0
    save_count = 0
    last_fps_time = time.time()
    fps_frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to read a frame - stream may have dropped. Retrying...")
            cap.release()
            time.sleep(1)
            cap = cv2.VideoCapture(STREAM_URL)
            continue

        frame_count += 1
        fps_frame_count += 1

        markers = detector.detect_markers(frame, depth_image=None)
        output = detector.draw_markers_on_image(frame, markers)

        cv2.putText(output, f"Markers detected: {len(markers)}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # Simple rolling FPS counter, printed once a second
        if time.time() - last_fps_time >= 1.0:
            fps = fps_frame_count / (time.time() - last_fps_time)
            cv2.putText(output, f"FPS: {fps:.1f}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            last_fps_time = time.time()
            fps_frame_count = 0

        cv2.imshow("ESP32-S3 Aruco Detection", output)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            classification = detector.classify_landing_zones(markers)
            cv2.imwrite(f"esp32_aruco_{save_count}.jpg", output)
            with open(f"esp32_aruco_{save_count}.json", "w") as f:
                json.dump(classification, f, indent=2)
            print(f"Saved esp32_aruco_{save_count}.jpg and .json")
            save_count += 1

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
