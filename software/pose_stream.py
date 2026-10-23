#!/usr/bin/env python3
"""
Live ArUco distance + bearing from the ESP32 stream.

Needs camera_calib.json from calibrate.py, and the printed marker's side
length (outer black border to outer black border), measured with a ruler.

Usage:
    python3 pose_stream.py --marker-mm 77
    python3 pose_stream.py --marker-mm 77 --source 0 --dict DICT_4X4_50

    # distances from the rover's centre instead of the camera lens:
    python3 pose_stream.py --marker-mm 77 --cam-forward-mm 120 --cam-right-mm 0

Camera mount (measured on the rover, lens relative to the rover's centre):
    --cam-forward-mm  how far in front of the centre the lens is (+ = ahead)
    --cam-right-mm    how far right of the centre line (+ = right, - = left)
    --cam-yaw-deg     if the camera is turned, how far (+ = turned right)

Keys: q = quit, s = log one row per visible marker to pose_log.csv along
with the true distance/angle you type in, to measure the error.

Bearing: 0 = straight ahead, + = marker to the right, - = to the left.
See marker_pose.py for the other fields.
"""

import argparse
import csv
import os
import time

import cv2

from marker_pose import MarkerPoseEstimator, load_calibration
from range_test import LatestFrameReader, STREAM_URL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=STREAM_URL, help="stream URL, or a webcam index like 0")
    ap.add_argument("--marker-mm", type=float, required=True,
                    help="printed marker side length in mm (black border to border)")
    ap.add_argument("--dict", default="DICT_6X6_250", help="ArUco dictionary of your markers")
    ap.add_argument("--calib", default="camera_calib.json")
    ap.add_argument("--log", default="pose_log.csv")
    ap.add_argument("--cam-forward-mm", type=float, default=None,
                    help="lens position ahead of the rover centre; enables rover-centre output")
    ap.add_argument("--cam-right-mm", type=float, default=None,
                    help="lens position right of the rover centre line (- = left)")
    ap.add_argument("--cam-yaw-deg", type=float, default=None,
                    help="camera turned right of the rover's nose (- = left)")
    args = ap.parse_args()

    mount_args = (args.cam_forward_mm, args.cam_right_mm, args.cam_yaw_deg)
    mount = None if all(v is None for v in mount_args) else tuple(v or 0.0 for v in mount_args)

    source = int(args.source) if args.source.isdigit() else args.source
    print(f"Opening {source} ...")
    reader = LatestFrameReader(source)
    frame, last_id = reader.read_new(0, timeout=10)
    if frame is None:
        print("No frames received. Check the ESP32 IP / Wi-Fi, and close any browser tab on /stream.")
        reader.stop()
        return
    h, w = frame.shape[:2]
    K, dist, _ = load_calibration(args.calib, (w, h))
    est = MarkerPoseEstimator(K, dist, args.marker_mm, getattr(cv2.aruco, args.dict), mount)
    print(f"Stream OK: {w}x{h}. Marker {args.marker_mm} mm, {args.dict}. q = quit, s = log.")
    if mount:
        print(f"Reporting from the rover centre: lens {mount[0]:+.0f} mm forward, "
              f"{mount[1]:+.0f} mm right, turned {mount[2]:+.1f} deg.")
    else:
        print("Reporting from the camera lens (no --cam-* mount given).")
    origin = "rover centre" if mount else "camera lens"
    rng, brg = ("rover_range_mm", "rover_bearing_deg") if mount else ("range_mm", "bearing_deg")

    last_print = 0.0
    try:
        while True:
            new, last_id = reader.read_new(last_id, timeout=2.0)
            if new is None:
                print("Stream stalled (no new frame in 2 s).")
                continue
            frame = new
            markers = est.detect(frame)
            cv2.imshow("Marker distance + bearing", est.draw(frame, markers))

            if time.time() - last_print >= 0.5 and markers:
                last_print = time.time()
                print("  ".join(f"ID {m['marker_id']}: {m[rng]:.0f} mm, "
                                f"{m[brg]:+.1f} deg from {origin}, reproj {m['reproj_err_px']:.2f} px"
                                for m in markers if m["valid"]))

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord('s') and markers:
                true_mm = input(f"True distance (mm, {origin} to marker centre): ").strip()
                true_deg = input("True bearing (deg, + = right, blank = 0): ").strip() or "0"
                new_file = not os.path.exists(args.log)
                with open(args.log, "a", newline="") as f:
                    log = csv.writer(f)
                    if new_file:
                        log.writerow(["time", "marker_id", "measured_from", "true_mm", "true_deg",
                                      "range_mm", "forward_mm", "bearing_deg",
                                      "rover_range_mm", "rover_bearing_deg",
                                      "reproj_err_px", "side_px", "resolution", "marker_mm",
                                      "dictionary", "cam_mount_fwd_right_yaw"])
                    for m in markers:
                        if m["valid"]:
                            log.writerow([time.strftime("%H:%M:%S"), m["marker_id"], origin,
                                          true_mm, true_deg,
                                          m["range_mm"], m["forward_mm"], m["bearing_deg"],
                                          m.get("rover_range_mm", ""), m.get("rover_bearing_deg", ""),
                                          m["reproj_err_px"], m["side_px"], f"{w}x{h}",
                                          args.marker_mm, args.dict,
                                          " ".join(f"{v:g}" for v in mount) if mount else ""])
                print(f"Logged to {args.log}")
    finally:
        reader.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
