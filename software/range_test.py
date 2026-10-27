#!/usr/bin/env python3
"""
Find the maximum distance at which an ArUco marker is still detected.

At each distance you type in, the script grabs N fresh frames, counts how
many detected the marker, measures the marker's side length in pixels, and
appends a row to range_results.csv. A sample frame is saved per distance.

Usage:
    python3 range_test.py                        # ESP32 stream (ESP32_IP below)
    python3 range_test.py --source 0             # laptop webcam instead
    python3 range_test.py --dict DICT_4X4_50 --frames 100 --marker-cm 10

Procedure: tape the marker flat, face it square to the camera at the same
height, start close (30 cm) and step back 25-50 cm at a time. Keep going
until the detection rate falls below ~50%; the last distance at >=90% is
your reliable range.
"""

import argparse
import csv
import os
import threading
import time

import cv2
import numpy as np

ESP32_IP = "172.20.10.5"
STREAM_URL = f"http://{ESP32_IP}/stream"


class LatestFrameReader:
    """Reads the stream in a background thread and keeps only the newest
    frame, so OpenCV's internal buffering doesn't hand us stale frames."""

    def __init__(self, source):
        self.source = source
        self.cap = cv2.VideoCapture(source)
        self.lock = threading.Lock()
        self.frame = None
        self.frame_id = 0
        self.frame_time = 0.0   # time.time() when the newest frame arrived
        self.read_time = 0.0    # arrival time of the frame last returned by read_new
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.5)
                self.cap.release()
                self.cap = cv2.VideoCapture(self.source)
                continue
            with self.lock:
                self.frame = frame
                self.frame_id += 1
                self.frame_time = time.time()

    def read_new(self, last_id, timeout=2.0):
        """Wait for a frame newer than last_id."""
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                if self.frame is not None and self.frame_id != last_id:
                    self.read_time = self.frame_time
                    return self.frame.copy(), self.frame_id
            time.sleep(0.005)
        return None, last_id

    def stop(self):
        self.running = False
        self.cap.release()


def side_px(corners):
    c = corners.reshape(4, 2)
    return float(np.mean([np.linalg.norm(c[i] - c[(i + 1) % 4]) for i in range(4)]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=STREAM_URL,
                    help="stream URL, or a webcam index like 0")
    ap.add_argument("--dict", default="DICT_6X6_250",
                    help="ArUco dictionary your printed markers use")
    ap.add_argument("--frames", type=int, default=100, help="frames per distance")
    ap.add_argument("--marker-cm", type=float, default=None,
                    help="printed marker side length (black border to border), for the log")
    ap.add_argument("--out", default="range_results.csv")
    args = ap.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, args.dict))
    detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

    print(f"Opening {source} ...")
    reader = LatestFrameReader(source)
    frame, last_id = reader.read_new(0, timeout=10)
    if frame is None:
        print("No frames received. Check the ESP32 IP / Wi-Fi, and close any browser tab on /stream.")
        reader.stop()
        return
    h, w = frame.shape[:2]
    print(f"Stream OK: {w}x{h}. Dictionary {args.dict}.")

    new_file = not os.path.exists(args.out)
    f = open(args.out, "a", newline="")
    log = csv.writer(f)
    if new_file:
        log.writerow(["distance_cm", "frames", "detected", "rate_pct", "ids_seen",
                      "mean_side_px", "min_side_px", "rejected_per_frame",
                      "resolution", "fps", "marker_cm", "dictionary"])

    try:
        while True:
            entry = input("\nDistance in cm (blank to quit): ").strip()
            if not entry:
                break
            dist = float(entry)

            detected, rejected_total, sides, ids_seen = 0, 0, [], set()
            sample, last_frame = None, frame
            t0 = time.time()
            for _ in range(args.frames):
                frame, last_id = reader.read_new(last_id)
                if frame is None:
                    print("Stream stalled; stopping this distance early.")
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                corners, ids, rejected = detector.detectMarkers(gray)
                rejected_total += len(rejected)
                if ids is not None and len(ids) > 0:
                    detected += 1
                    ids_seen.update(int(i) for i in ids.flatten())
                    sides.append(max(side_px(c) for c in corners))
                    if sample is None:
                        sample = frame.copy()
                        cv2.aruco.drawDetectedMarkers(sample, corners, ids)
                if sample is None:
                    last_frame = frame
            elapsed = time.time() - t0
            n = args.frames
            rate = 100.0 * detected / n
            fps = n / elapsed if elapsed > 0 else 0.0

            row = [dist, n, detected, round(rate, 1), " ".join(map(str, sorted(ids_seen))),
                   round(np.mean(sides), 1) if sides else "", round(min(sides), 1) if sides else "",
                   round(rejected_total / n, 2), f"{w}x{h}", round(fps, 1),
                   args.marker_cm or "", args.dict]
            log.writerow(row)
            f.flush()

            img = sample if sample is not None else last_frame
            name = f"range_{int(dist)}cm.jpg"
            cv2.imwrite(name, img)
            side_txt = f"{np.mean(sides):.0f}px" if sides else "-"
            print(f"{dist:.0f} cm: {detected}/{n} detected ({rate:.0f}%), "
                  f"marker side {side_txt}, rejected/frame {rejected_total / n:.1f}, "
                  f"{fps:.1f} fps -> saved {name}")
            if rate < 50:
                print("Below 50%: you're past the reliable range. "
                      "High rejected count = marker seen but too few pixels to decode.")
    finally:
        f.close()
        reader.stop()
        print(f"Results in {args.out}")


if __name__ == "__main__":
    main()
