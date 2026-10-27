#!/usr/bin/env python3
"""
Minimal consumer of the vision feed (stdin, one JSON message per line):
drops repeated/old frames and stale messages, notices detector restarts,
and prints health changes and usable markers. A starting point for B1's
side, not the arrival logic itself.

Usage:
    python3 laptop/vision_publisher.py --marker-mm 77 --stdout --no-view | python3 laptop/receiver_example.py
    python3 laptop/replay.py session1.jsonl | python3 laptop/receiver_example.py
"""

import json
import sys
import time

MAX_AGE_MS = 500  # older than this at consumption -> stale (proposed, agree with B1)


def main():
    session, last_seq, last_status = None, -1, None
    for line in sys.stdin:
        msg = json.loads(line)
        if msg["source_session_id"] != session:
            print(f"New detector session {msg['source_session_id']} (restart): reset state")
            session, last_seq = msg["source_session_id"], -1
        if msg["status"] != last_status:
            print(f"Health: {msg['status']} (last frame {msg['last_frame_age_ms']} ms old)")
            last_status = msg["status"]
        if msg["status"] not in ("ok", "no_marker"):
            continue
        if msg["frame_seq"] <= last_seq:
            continue  # repeat or out of order
        last_seq = msg["frame_seq"]
        # Same-clock assumption: publisher and receiver on one laptop (or replay.py retimed).
        age = int(time.time() * 1000) - msg["capture_time_ms"]
        if age > MAX_AGE_MS:
            print(f"seq {last_seq}: stale ({age} ms), ignored")
            continue
        for m in msg["markers"]:
            if m["valid"]:
                print(f"seq {last_seq}: ID {m['marker_id']} {m['marker_type']} "
                      f"{m['distance_mm']:.0f} mm {m['bearing_deg']:+.1f} deg ({m['distance_ref']}), age {age} ms")


if __name__ == "__main__":
    main()
