#!/usr/bin/env python3
"""Try every common ArUco/AprilTag dictionary against a single saved debug
frame to figure out which one your printed markers actually belong to.

Usage:
    python3 dict_finder.py debug_gray_84.jpg
(pass whichever debug_gray_*.jpg you already saved from debug_aruco.py)
"""

import sys
import cv2

CANDIDATES = [
    "DICT_4X4_50", "DICT_4X4_100", "DICT_4X4_250", "DICT_4X4_1000",
    "DICT_5X5_50", "DICT_5X5_100", "DICT_5X5_250", "DICT_5X5_1000",
    "DICT_6X6_50", "DICT_6X6_100", "DICT_6X6_250", "DICT_6X6_1000",
    "DICT_7X7_50", "DICT_7X7_100", "DICT_7X7_250", "DICT_7X7_1000",
    "DICT_ARUCO_ORIGINAL",
    "DICT_APRILTAG_16h5", "DICT_APRILTAG_25h9",
    "DICT_APRILTAG_36h10", "DICT_APRILTAG_36h11",
]

if len(sys.argv) < 2:
    print("Usage: python3 dict_finder.py <path_to_debug_gray_image.jpg>")
    sys.exit(1)

img_path = sys.argv[1]
img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
if img is None:
    print(f"Could not load image: {img_path}")
    sys.exit(1)

print(f"Testing {len(CANDIDATES)} dictionaries against {img_path} ...\n")

best = None
for name in CANDIDATES:
    dict_id = getattr(cv2.aruco, name)
    aruco_dict = cv2.aruco.getPredefinedDictionary(dict_id)
    params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, params)
    corners, ids, rejected = detector.detectMarkers(img)

    n_detected = 0 if ids is None else len(ids)
    n_rejected = len(rejected)
    marker_ids = ids.flatten().tolist() if ids is not None else []

    marker = "  <-- MATCH" if n_detected > 0 else ""
    print(f"{name:26s} detected={n_detected:2d}  rejected={n_rejected:3d}  ids={marker_ids}{marker}")

    if n_detected > 0 and best is None:
        best = name

print()
if best:
    print(f"✓ Best match: {best}")
    print(f"  Update ARUCO_DICT_TYPE in debug_aruco.py to: cv2.aruco.{best}")
else:
    print("❌ No dictionary detected anything on this image.")
    print("   This points away from a dictionary mismatch and toward something")
    print("   else - e.g. missing white quiet-zone margin around each marker,")
    print("   markers too small/low-res in frame, or markers from a generator")
    print("   that doesn't match any standard OpenCV dictionary.")
