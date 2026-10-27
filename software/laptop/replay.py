#!/usr/bin/env python3
"""
Play a recorded vision_publisher.py session (.jsonl) back to stdout at its
original pace, so B1 can test without the camera.

Usage:
    python3 laptop/replay.py session1.jsonl | python3 laptop/receiver_example.py
    python3 laptop/replay.py session1.jsonl --speed 2 --keep-times

Timestamps are shifted so the first message reads as "now" (so freshness
checks pass); --keep-times leaves the recorded times unchanged.
"""

import argparse
import json
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--keep-times", action="store_true")
    args = ap.parse_args()

    with open(args.file) as f:
        msgs = [json.loads(line) for line in f if line.strip()]
    if not msgs:
        return
    t0_rec, t0_wall = msgs[0]["processed_time_ms"], time.time() * 1000
    for msg in msgs:
        due = t0_wall + (msg["processed_time_ms"] - t0_rec) / args.speed
        time.sleep(max(0.0, (due - time.time() * 1000) / 1000))
        if not args.keep_times:
            shift = int(time.time() * 1000) - msg["processed_time_ms"]
            msg["capture_time_ms"] += shift
            msg["processed_time_ms"] += shift
        print(json.dumps(msg), flush=True)


if __name__ == "__main__":
    main()
