#!/usr/bin/env python3
"""
Camera calibration for the ESP32 stream, using a printed chessboard.

Distance from a marker depends on the camera's focal length and lens
distortion, so this has to be done once per camera + stream resolution.
Re-run it if you change the webcam, its resolution, or its focus.

Usage:
    python3 calibrate.py --make-board            # writes chessboard_9x6.png to print
    python3 calibrate.py                         # calibrate from the ESP32 stream
    python3 calibrate.py --source 0              # laptop webcam instead

Procedure: print the board (or show it full-screen on a tablet), keep it
flat. The window shows a 3x3 guide grid with the next target cell
highlighted and an instruction at the bottom. Put the board there, and
press SPACE when the corners are drawn in colour. 'n' skips a shot,
'c' calibrates and saves, 'q' quits.
A good result has RMS reprojection error below ~0.5 px.
"""

import argparse
import json
import time

import cv2
import numpy as np

from range_test import LatestFrameReader, STREAM_URL


# Guided shot list: (cell, how to hold the board). Covering every cell,
# several distances and some tilts is what pins down the lens distortion.
CELLS = {"top-left": (0, 0), "top": (0, 1), "top-right": (0, 2),
         "left": (1, 0), "centre": (1, 1), "right": (1, 2),
         "bottom-left": (2, 0), "bottom": (2, 1), "bottom-right": (2, 2)}
SHOTS = [
    ("centre", "flat, board fills ~1/3 of the frame"),
    ("centre", "flat, CLOSE - board fills most of the frame"),
    ("centre", "flat, FAR - board is small"),
    ("top-left", "flat"), ("top-right", "flat"),
    ("bottom-left", "flat"), ("bottom-right", "flat"),
    ("top", "flat"), ("bottom", "flat"), ("left", "flat"), ("right", "flat"),
    ("centre", "turn ~30 deg: left edge further away"),
    ("centre", "turn ~30 deg: right edge further away"),
    ("centre", "tilt ~30 deg: top edge further away"),
    ("centre", "tilt ~30 deg: bottom edge further away"),
    ("top-left", "tilted any way"), ("top-right", "tilted any way"),
    ("bottom-left", "tilted any way"), ("bottom-right", "tilted any way"),
    ("centre", "rotated to portrait"),
]


def cell_of(corners, w, h):
    cx, cy = corners.reshape(-1, 2).mean(axis=0)
    return min(int(cy * 3 / h), 2), min(int(cx * 3 / w), 2)


def draw_guide(view, shot, coverage, board_cell):
    """3x3 grid, highlighted target cell, per-cell view counts, instruction."""
    h, w = view.shape[:2]
    cw, ch = w // 3, h // 3
    if shot < len(SHOTS):
        r, c = CELLS[SHOTS[shot][0]]
        x0, y0 = c * cw, r * ch
        roi = view[y0:y0 + ch, x0:x0 + cw]
        roi[:] = cv2.addWeighted(roi, 0.75, np.full_like(roi, (0, 200, 255)), 0.25, 0)
        cv2.rectangle(view, (x0 + 2, y0 + 2), (x0 + cw - 2, y0 + ch - 2), (0, 200, 255), 3)
    for i in (1, 2):
        cv2.line(view, (i * cw, 0), (i * cw, h), (255, 255, 255), 1)
        cv2.line(view, (0, i * ch), (w, i * ch), (255, 255, 255), 1)
    for (r, c), n in coverage.items():
        cv2.putText(view, f"{n}", (c * cw + cw - 30, r * ch + ch - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    if shot < len(SHOTS):
        cell, how = SHOTS[shot]
        msg = f"Shot {shot + 1}/{len(SHOTS)}: {cell.upper()}, {how}"
        if board_cell is not None:
            msg += "  [in target]" if board_cell == CELLS[cell] else "  [move to highlighted cell]"
    else:
        msg = "All shots done - press c to calibrate"
    (tw, th), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(view, (0, h - th - 20), (min(tw + 20, w), h), (0, 0, 0), -1)
    cv2.putText(view, msg, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)


def make_board(cols, rows, square_px=120, path=None):
    """Board with cols x rows INNER corners = (cols+1) x (rows+1) squares."""
    sq = np.indices((rows + 1, cols + 1)).sum(axis=0) % 2
    img = (sq * 255).astype(np.uint8).repeat(square_px, 0).repeat(square_px, 1)
    img = cv2.copyMakeBorder(img, square_px, square_px, square_px, square_px,
                             cv2.BORDER_CONSTANT, value=255)
    path = path or f"chessboard_{cols}x{rows}.png"
    cv2.imwrite(path, img)
    print(f"Wrote {path}. Print it at 100% scale and glue it to something flat.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=STREAM_URL, help="stream URL, or a webcam index like 0")
    ap.add_argument("--cols", type=int, default=9, help="inner corners per row")
    ap.add_argument("--rows", type=int, default=6, help="inner corners per column")
    ap.add_argument("--square-mm", type=float, default=25.0,
                    help="measured printed square size (does not affect intrinsics)")
    ap.add_argument("--min-views", type=int, default=12)
    ap.add_argument("--out", default="camera_calib.json")
    ap.add_argument("--make-board", action="store_true")
    args = ap.parse_args()

    if args.make_board:
        make_board(args.cols, args.rows)
        return

    pattern = (args.cols, args.rows)
    objp = np.zeros((args.rows * args.cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:args.cols, 0:args.rows].T.reshape(-1, 2) * args.square_mm

    source = int(args.source) if args.source.isdigit() else args.source
    print(f"Opening {source} ...")
    reader = LatestFrameReader(source)
    frame, last_id = reader.read_new(0, timeout=10)
    if frame is None:
        print("No frames received. Check the ESP32 IP / Wi-Fi, and close any browser tab on /stream.")
        reader.stop()
        return
    h, w = frame.shape[:2]
    print(f"Stream OK: {w}x{h}. SPACE = grab view, n = skip shot, c = calibrate, q = quit.")

    obj_points, img_points = [], []
    shot, coverage = 0, {}
    try:
        while True:
            new, last_id = reader.read_new(last_id, timeout=0.5)
            if new is not None:
                frame = new
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found, corners = cv2.findChessboardCornersSB(gray, pattern)

            view = frame.copy()
            draw_guide(view, shot, coverage, cell_of(corners, w, h) if found else None)
            if found:
                cv2.drawChessboardCorners(view, pattern, corners, found)
            cv2.putText(view, f"views: {len(obj_points)}/{args.min_views}  "
                              f"{'BOARD FOUND' if found else 'no board'}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 255, 0) if found else (0, 0, 255), 2)
            cv2.imshow("Calibration", view)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord(' ') and found:
                obj_points.append(objp)
                img_points.append(corners)
                cell = cell_of(corners, w, h)
                coverage[cell] = coverage.get(cell, 0) + 1
                print(f"Grabbed view {len(obj_points)}")
                shot += 1
            if key == ord('n') and shot < len(SHOTS):
                print(f"Skipped shot {shot + 1}: {SHOTS[shot][0]}, {SHOTS[shot][1]}")
                shot += 1
            if key == ord('c'):
                if len(obj_points) < args.min_views:
                    print(f"Need at least {args.min_views} views, have {len(obj_points)}.")
                    continue
                rms, K, dist, _, _ = cv2.calibrateCamera(obj_points, img_points, (w, h), None, None)
                calib = {
                    "width": w, "height": h,
                    "camera_matrix": K.tolist(),
                    "dist_coeffs": dist.flatten().tolist(),
                    "rms_reproj_px": round(float(rms), 4),
                    "views": len(obj_points),
                    "board": {"cols": args.cols, "rows": args.rows, "square_mm": args.square_mm},
                    "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                with open(args.out, "w") as f:
                    json.dump(calib, f, indent=2)
                print(f"RMS reprojection error {rms:.3f} px "
                      f"({'good' if rms < 0.5 else 'OK' if rms < 1.0 else 'poor - retake views'}). "
                      f"fx={K[0, 0]:.1f} fy={K[1, 1]:.1f} cx={K[0, 2]:.1f} cy={K[1, 2]:.1f}")
                print(f"Saved {args.out}")
                break
    finally:
        reader.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
