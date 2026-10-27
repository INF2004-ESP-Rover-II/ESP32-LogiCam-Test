# Vision feed: proposed contract (B3 → B1, B5)

Draft, 27 Oct 2026. The fields below are what `software/laptop/vision_publisher.py`
already sends. Transport, numbers marked *proposed*, and the arrival rules
need agreement from B1 and B5.

## How to run it

```
cd software
# live, distances from the rover centre, recording a session
python3 laptop/vision_publisher.py --marker-mm 77 --cam-forward-mm 120 --cam-right-mm 0 --record session1.jsonl
# feed piped into the example receiver
python3 laptop/vision_publisher.py --marker-mm 77 --cam-forward-mm 120 --cam-right-mm 0 --stdout --no-view | python3 laptop/receiver_example.py
# replay a recorded session (no camera needed)
python3 laptop/replay.py session1.jsonl | python3 laptop/receiver_example.py
```

Transport today: one JSON object per line on stdout and/or a `.jsonl` file.
Detection runs on the laptop, reading the ESP32-S3 MJPEG stream over Wi-Fi.

## Message (one per processed frame)

```json
{"schema": 1, "source_session_id": "cc374b6a", "frame_seq": 114,
 "capture_time_ms": 1793098912605, "capture_time_source": "laptop_receive",
 "processed_time_ms": 1793098912607, "status": "ok", "last_frame_age_ms": 2,
 "markers": [{"marker_id": 1, "marker_type": "junction", "valid": true, "reject_reason": "",
   "distance_mm": 627.1, "bearing_deg": 4.6, "distance_ref": "rover_centre",
   "camera_range_mm": 507.6, "camera_forward_mm": 505.1, "camera_bearing_deg": 5.69,
   "reproj_err_px": 0.241, "side_px": 128.3}]}
```

| Field | Meaning |
|---|---|
| `source_session_id` | Random per publisher run. A new value = detector restarted; drop old state. |
| `frame_seq` | Frame counter from the stream reader. Rises with every received frame; gaps mean frames were skipped (only the newest is processed). A repeat means no new frame. |
| `capture_time_ms` | Unix ms when the frame **arrived on the laptop** (`capture_time_source: laptop_receive`). The ESP32 does not timestamp frames, so true capture is earlier by the Wi-Fi/encode delay (not yet measured). |
| `processed_time_ms` | Unix ms after detection finished. |
| `status` | `ok` (≥1 marker seen), `no_marker` (fresh frame, nothing in it), `stalled` (no new frame ≥ 1 s), `disconnected` (no new frame ≥ 5 s). |
| `last_frame_age_ms` | How old the newest frame is at send time. Health messages repeat every 0.2 s while stalled; they keep the old `frame_seq` and `capture_time_ms`, so they never look like a fresh image. |
| `markers[]` | Every marker in the frame (empty in health messages). Several can appear at once. |
| `marker_id` | Decoded ArUco ID (DICT_6X6_250). 0 is a real ID. |
| `marker_type` | `plain` / `junction` from `software/laptop/markers.json`, `unknown` if not listed. **IDs are placeholders: B1 to supply the real list.** |
| `valid`, `reject_reason` | `false` with `pose_failed`, `high_reproj_error` (> 1.0 px at 640 wide, scaled with resolution: 3.0 px at 1920), `too_small` (< 20 px side) or `too_far` (> 1500 mm). *Proposed cut-offs.* |
| `distance_mm` | Horizontal distance **rover centre → marker centre** when `distance_ref` is `rover_centre` (camera mount given), otherwise straight-line **camera lens → marker centre** (`camera_lens`). |
| `bearing_deg` | 0 = straight ahead, **+ = right**, − = left. Same frame as `distance_ref` (rover or camera). Not rover heading. |
| `camera_*` | Raw camera-frame values: range, depth along the lens axis, bearing. |
| `reproj_err_px`, `side_px` | Fit quality and marker size in pixels. |

Clocks: times are the **laptop's** clock. Age = laptop now − `capture_time_ms`
only works on the laptop. If the Pico consumes it, B5's transport should
convert to an age at send time (or use `last_frame_age_ms`) rather than
subtracting uptimes.

## Calibration and accuracy (B3 measured)

- Logitech webcam, 640×480, calibrated (`camera_calib.json`, RMS 0.13 px).
- Marker 77 mm. Camera lens 120 mm ahead of the rover centre, on the centre line.
- Error seen: about ±1–2 cm up to 60 cm, ±2–4 cm to 100 cm, bearing ±1–2°.
  Detected up to 120 cm at an angle. Full log (`pose_log.csv`) still to do.
- Assumes the camera is level. Camera tilt/height for floor markers not added yet.
- Delay from capture to message: not measured yet.

## Proposed arrival rules (for B1 to accept or change)

B3 sends observations only; B1's executor decides arrival, as B1 asked.

1. **Usable observation:** `status` `ok`, `valid` true, age ≤ 500 ms.
2. **Arrival candidate:** `distance_mm` within ±30 mm of the agreed stop
   distance and |`bearing_deg`| ≤ 5°, for **5 consecutive usable frames**
   of the same ID.
3. **One per visit:** after an arrival, that ID is locked until it has been
   absent (or > stop distance + 150 mm) for ≥ 1 s **of healthy frames**.
   Stalled/disconnected time does not count as leaving.
4. **Revisits:** once re-armed, the same ID can arrive again.
5. **Several markers:** pick the valid one with the smallest |bearing|;
   ignore the segment's source marker until it is re-armed.
6. **Known target:** if the segment expects an ID and another one meets
   rule 2, report "unexpected marker"; do not finish the segment.
7. **Faults:** `stalled` → B1/B4 hold or stop per the agreed policy;
   `disconnected` or a new `source_session_id` → cancel the active segment.

## Sample messages

`software/laptop/home_2markers.jsonl`: 186 s, 4,802 messages, iPhone camera at
1920×1080 (`distance_ref: camera_lens`, no rover mount). Two markers (ID 1, ID 2),
held still, moved, hidden, plus two frozen-feed tests (stalled at 1.02 s,
disconnected at 5.1 s, then recovered). One of each status:

```json
{"frame_seq": 2, "status": "no_marker", "last_frame_age_ms": 9, "markers": [], ...}
{"frame_seq": 4307, "status": "stalled", "last_frame_age_ms": 1021, "markers": [], ...}
{"frame_seq": 4307, "status": "disconnected", "last_frame_age_ms": 5139, "markers": [], ...}
```

Known in that recording: 1–3-frame detection dropouts while the marker is still,
and two single-frame jumps of 5–8 cm that pass the quality check. Rule 2's
5-frame stability and rule 3's 1 s absence are meant to absorb both.

## Notes for B1's current controller

- **Camera points forward, not down.** Mounted level at the front, 120 mm ahead
  of the rover centre, on the centre line. Markers are read ahead of the rover,
  so the stop is a distance to the marker, not "marker under the camera".
- **Marker table:** `markers.json` is placeholder. If all IDs 1–36 are
  junctions, that is the table; send the final list and it gets updated.
- **Restarts:** every publisher start gets a new `source_session_id` and
  `frame_seq` starts again from 0. Compare `frame_seq` only within one session.
- **Timeouts:** `stalled` is sent at 1 s, matching the controller's 1 s pause.
  `disconnected` (5 s) is for cancelling, not for the first stop.

## Open questions

- **B5:** transport (MQTT topic / UDP / serial to Pico?), rate, and where
  the age is computed.
- **B1:** marker ID → plain/junction list; the stop point relative to the
  marker (so the stop distance in rule 2 can be fixed).
- **All:** confirm the 500 ms / 1 s / 5 s timeouts once delay is measured.
