#!/usr/bin/env python3
import argparse
import os
import time
from datetime import datetime

import serial

import tdma_hub as hub
from har_dataset_utils import (
    ACTIVITIES,
    FEATURE_KEYS,
    NODE_LAYOUT,
    default_dataset_root,
    ensure_dir,
    local_now_iso,
    sanitize_token,
    write_json,
    append_jsonl,
)


class NodeReader:
    def __init__(self, node_id, timeout):
        self.node_id = node_id
        self.port = hub.NODE_PORTS[node_id]
        self.timeout = timeout
        self.serial = None
        self.next_retry_at = 0.0
        self.error_count = 0

    def close(self):
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass

        self.serial = None

    def open(self):
        if self.serial is not None and getattr(self.serial, "is_open", False):
            return True

        now = time.monotonic()

        if now < self.next_retry_at:
            return False

        try:
            self.serial = serial.Serial(
                self.port,
                hub.BAUDRATE,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
            time.sleep(0.15)
            return True
        except Exception as error:
            self.error_count += 1
            self.next_retry_at = now + min(5.0, 0.5 * self.error_count)
            print(f"[node {self.node_id}] open failed on {self.port}: {error}", flush=True)
            self.close()
            return False

    def request_sample(self):
        if not self.open():
            return None, "open_failed"

        try:
            self.serial.write(b"R")
            self.serial.flush()
            line = self.serial.readline().decode(errors="ignore").strip()
        except Exception as error:
            self.error_count += 1
            self.next_retry_at = time.monotonic() + min(5.0, 0.5 * self.error_count)
            print(f"[node {self.node_id}] read failed: {error}", flush=True)
            self.close()
            return None, "read_failed"

        if not line:
            return None, "empty"

        parsed = hub.parse_frame(line)

        if parsed is None:
            return {"raw_line": line}, "parse_failed"

        if int(parsed["node_id"]) != self.node_id:
            return {"raw_line": line, "parsed_node_id": parsed["node_id"]}, "wrong_node"

        self.error_count = 0
        return parsed, "ok"


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Collect raw HAR samples from the three ESP32 nodes.")
    parser.add_argument("--participant", required=True, help="Participant id, e.g. p01")
    parser.add_argument("--activity", required=True, choices=ACTIVITIES)
    parser.add_argument("--duration", required=True, type=float, help="Recorded seconds after warmup")
    parser.add_argument("--notes", default="")
    parser.add_argument("--warmup", type=float, default=5.0)
    parser.add_argument("--dataset-root", default=default_dataset_root())
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--poll-sleep", type=float, default=0.02)
    return parser


def main():
    args = build_arg_parser().parse_args()
    participant = sanitize_token(args.participant)
    activity = sanitize_token(args.activity)
    started = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"session_{started}_{participant}_{activity}"
    session_dir = ensure_dir(os.path.join(args.dataset_root, "raw_sessions", session_id))
    metadata_path = os.path.join(session_dir, "metadata.json")
    samples_path = os.path.join(session_dir, "raw_samples.jsonl")

    metadata = {
        "session_id": session_id,
        "participant_id": participant,
        "activity": activity,
        "started_at": local_now_iso(),
        "duration_seconds": float(args.duration),
        "warmup_seconds": float(args.warmup),
        "node_layout": NODE_LAYOUT,
        "node_ports": {str(node_id): hub.NODE_PORTS[node_id] for node_id in hub.NODE_PORTS},
        "features": list(FEATURE_KEYS),
        "notes": args.notes,
        "status": "running",
    }
    write_json(metadata_path, metadata)

    readers = {node_id: NodeReader(node_id, args.timeout) for node_id in (1, 2, 3)}
    status_counts = {}
    sample_count = 0
    warmup_until = time.monotonic() + max(0.0, args.warmup)
    stop_at = warmup_until + max(0.0, args.duration)

    print(f"Session: {session_id}")
    print(f"Warmup: {args.warmup:.1f}s, recording: {args.duration:.1f}s")
    print(f"Writing: {samples_path}")

    try:
        with open(samples_path, "a", encoding="utf-8") as samples_file:
            while time.monotonic() < stop_at:
                now = time.monotonic()
                collecting = now >= warmup_until

                for node_id, reader in readers.items():
                    parsed, status = reader.request_sample()
                    status_counts[status] = status_counts.get(status, 0) + 1

                    if not collecting or status != "ok":
                        continue

                    entry = {
                        "session_id": session_id,
                        "participant_id": participant,
                        "activity": activity,
                        "node_id": int(parsed["node_id"]),
                        "node_name": NODE_LAYOUT[str(parsed["node_id"])],
                        "t_device_ms": int(parsed["t"]),
                        "t_host": time.time(),
                    }

                    for feature in FEATURE_KEYS:
                        entry[feature] = float(parsed[feature])

                    append_jsonl(samples_file, entry)
                    sample_count += 1

                samples_file.flush()
                elapsed = max(0.0, time.monotonic() - warmup_until)
                print(
                    f"\rrecording={collecting} elapsed={elapsed:.1f}/{args.duration:.1f}s "
                    f"samples={sample_count} status={status_counts}",
                    end="",
                    flush=True,
                )
                time.sleep(max(0.0, args.poll_sleep))
    finally:
        for reader in readers.values():
            reader.close()

    print()
    metadata["finished_at"] = local_now_iso()
    metadata["status"] = "completed"
    metadata["sample_count"] = sample_count
    metadata["request_status_counts"] = status_counts
    write_json(metadata_path, metadata)
    print(f"Saved metadata: {metadata_path}")


if __name__ == "__main__":
    main()
