#!/usr/bin/env python3
"""Debug Aruco detection against your Mac's built-in/USB webcam instead of
the ESP32 stream - use this to check whether the detection code itself works
correctly, isolated from any ESP32/network/stream issues."""

import cv2
import numpy as np
import time

# 0 is normally the built-in FaceTime camera on a Mac. If you have another
# USB webcam plugged in, try 1, 2, etc. if 0 doesn't give the camera you want.
CAMERA_INDEX = 0

# Match this to whichever dictionary your printed/displayed markers use.
ARUCO_DICT_TYPE = cv2.aruco.DICT_4X4_250


class ArucoDebugger:
    def __init__(self):
        self.arucoDict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
        self.parameters = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(self.arucoDict, self.parameters)

    def check_camera(self):
        """Test if the local webcam is accessible"""
        cap = cv2.VideoCapture(CAMERA_INDEX)

        if not cap.isOpened():
            print(f"❌ Could not open local webcam at index {CAMERA_INDEX}!")
            print("   Check that:")
            print("   - No other app (Zoom, FaceTime, Photo Booth, etc.) is using the camera")
            print("   - macOS camera permissions are granted to your terminal/IDE")
            print("   - Try a different CAMERA_INDEX (0, 1, 2...) if you have multiple cameras")
            return False

        ret, frame = cap.read()
        cap.release()

        if ret:
            print(f"✓ Local webcam working! Frame size: {frame.shape}")
            return True
        else:
            print("❌ Camera opened but can't read frames")
            return False

    def test_detection(self, show_debug=True):
        """Live local webcam test with DEBUG INFO"""
        print("\n" + "="*70)
        print("ARUCO DETECTION DEBUG MODE (local webcam)")
        print("="*70)
        print(f"Camera index: {CAMERA_INDEX}")
        print("Instructions:")
        print("1. Print an Aruco marker (STRONGLY RECOMMENDED)")
        print("2. Or display on phone screen (at full brightness)")
        print("3. Show to camera at 20-50cm distance")
        print("4. Make sure the camera's lens is in focus (sharp image)")
        print("5. Press 'q' to quit, 's' to save frame")
        print("="*70 + "\n")

        cap = cv2.VideoCapture(CAMERA_INDEX)
        frame_count = 0
        detected_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                print("❌ Failed to read frame - camera may have dropped. Retrying...")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(CAMERA_INDEX)
                continue

            frame_count += 1
            height, width = frame.shape[:2]

            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Detect markers
            corners, ids, rejected = self.detector.detectMarkers(gray)

            # Draw on frame
            output = frame.copy()

            # Add frame info
            cv2.putText(output, f"Frame: {frame_count}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(output, f"Size: {width}x{height}", (10, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Detection results
            if ids is not None:
                print(f"✓ Frame {frame_count}: DETECTED {len(ids)} marker(s)! IDs: {ids.flatten().tolist()}")
                detected_count += 1

                # Draw all detected markers
                for corner, marker_id in zip(corners, ids.flatten()):
                    corner = corner.reshape((4, 2))
                    cv2.polylines(output, [corner.astype(int)], True, (0, 255, 0), 3)

                    cx = int(corner.mean(axis=0)[0])
                    cy = int(corner.mean(axis=0)[1])
                    cv2.circle(output, (cx, cy), 8, (0, 0, 255), -1)
                    cv2.putText(output, f"ID:{marker_id}", (cx-30, cy-30),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

                # Draw status
                cv2.putText(output, f"DETECTED: {len(ids)} markers", (10, 90),
                           cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            else:
                # Not detected
                cv2.putText(output, "NO MARKERS DETECTED", (10, 90),
                           cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

                # Show tips
                cv2.putText(output, "Try:", (10, 120),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 0), 1)
                cv2.putText(output, "- Adjust camera focus", (10, 145),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 0), 1)
                cv2.putText(output, "- Move marker 20-50cm from camera", (10, 170),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 0), 1)
                cv2.putText(output, "- Increase lighting", (10, 195),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 0), 1)

            # Show rejected markers (detected but not valid) - a high rejected
            # count with 0 detections is a strong sign of blur/focus issues,
            # since it means the detector IS finding quad-like shapes but
            # can't confirm the inner marker pattern.
            if len(rejected) > 0:
                cv2.putText(output, f"Rejected: {len(rejected)}", (10, 220),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 1)
                for corner in rejected:
                    corner = corner.reshape((4, 2))
                    cv2.polylines(output, [corner.astype(int)], True, (0, 165, 255), 2)

            cv2.imshow("Aruco Debug (local webcam)", output)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):
                cv2.imwrite(f"debug_frame_{frame_count}.jpg", output)
                cv2.imwrite(f"debug_gray_{frame_count}.jpg", gray)
                print(f"✓ Saved debug_frame_{frame_count}.jpg and debug_gray_{frame_count}.jpg")

        cap.release()
        cv2.destroyAllWindows()

        print("\n" + "="*70)
        print("DEBUG SUMMARY")
        print("="*70)
        print(f"Total frames captured: {frame_count}")
        print(f"Frames with detection: {detected_count}")
        if frame_count > 0:
            detection_rate = (detected_count / frame_count) * 100
            print(f"Detection rate: {detection_rate:.1f}%")

            if detection_rate == 0:
                print("\n⚠️  0% detection! Try these fixes:")
                print("   1. Adjust the camera's focus until the image is sharp")
                print("   2. Increase brightness")
                print("   3. Move marker 20-50cm away")
                print("   4. Check ARUCO_DICT_TYPE matches your actual marker")
        print("="*70 + "\n")


if __name__ == "__main__":
    debugger = ArucoDebugger()

    print("Checking local webcam...")
    if debugger.check_camera():
        debugger.test_detection()
    else:
        print("Please fix the local webcam connection first")
