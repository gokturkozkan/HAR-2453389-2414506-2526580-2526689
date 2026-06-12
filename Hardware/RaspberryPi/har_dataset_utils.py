import json
import math
import os
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np


NODE_IDS = (1, 2, 3)
NODE_LAYOUT = {
    "1": "wrist",
    "2": "chest",
    "3": "ankle",
}
FEATURE_KEYS = ("ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz")
WINDOW_SECONDS = 6.0
MODEL_TIMESTEPS = 200
NODE_ORDER = (1, 2, 3)
ACTIVITIES = ("standing", "sitting", "lying", "walking")


def raspberrypi_dir():
    return os.path.dirname(os.path.abspath(__file__))


def default_dataset_root():
    return os.path.join(raspberrypi_dir(), "datasets")


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def local_now_iso():
    return datetime.now().astimezone().isoformat()


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def read_json(path, default=None):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    ensure_dir(os.path.dirname(path))

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def append_jsonl(handle, data):
    handle.write(json.dumps(data, ensure_ascii=False, default=str))
    handle.write("\n")


def iter_jsonl(path):
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSONL row: {error}") from error


def safe_float(value):
    value = float(value)

    if not math.isfinite(value):
        raise ValueError(f"non-finite numeric value: {value}")

    return value


def sanitize_token(value):
    text = str(value).strip().lower()
    cleaned = []

    for char in text:
        if char.isalnum() or char in ("-", "_"):
            cleaned.append(char)
        elif char.isspace():
            cleaned.append("_")

    return "".join(cleaned).strip("_") or "unknown"


def load_raw_sessions(dataset_root=None):
    dataset_root = dataset_root or default_dataset_root()
    raw_root = os.path.join(dataset_root, "raw_sessions")

    if not os.path.isdir(raw_root):
        return []

    sessions = []

    for name in sorted(os.listdir(raw_root)):
        session_dir = os.path.join(raw_root, name)

        if not os.path.isdir(session_dir):
            continue

        metadata_path = os.path.join(session_dir, "metadata.json")
        samples_path = os.path.join(session_dir, "raw_samples.jsonl")

        if not os.path.exists(metadata_path) or not os.path.exists(samples_path):
            continue

        metadata = read_json(metadata_path, default={})
        sessions.append({
            "session_dir": session_dir,
            "metadata_path": metadata_path,
            "samples_path": samples_path,
            "metadata": metadata,
        })

    return sessions


def group_samples_by_node(samples):
    grouped = {node_id: [] for node_id in NODE_IDS}

    for sample in samples:
        node_id = int(sample["node_id"])

        if node_id not in grouped:
            continue

        row = {"t_host": safe_float(sample["t_host"])}

        for feature in FEATURE_KEYS:
            row[feature] = safe_float(sample.get(feature, 0.0))

        grouped[node_id].append(row)

    for node_id in NODE_IDS:
        grouped[node_id].sort(key=lambda item: item["t_host"])

    return grouped


def dedupe_times(rows):
    by_time = {}

    for row in rows:
        by_time[row["t_host"]] = row

    return [by_time[timestamp] for timestamp in sorted(by_time)]


def can_resample_node(rows, start_time, end_time):
    if len(rows) < 2:
        return False

    rows = dedupe_times(rows)

    if len(rows) < 2:
        return False

    return rows[0]["t_host"] <= start_time and rows[-1]["t_host"] >= end_time


def resample_node(rows, start_time, window_seconds=WINDOW_SECONDS, model_timesteps=MODEL_TIMESTEPS):
    end_time = start_time + window_seconds
    rows = dedupe_times(rows)

    if not can_resample_node(rows, start_time, end_time):
        return None

    source_times = np.asarray([row["t_host"] for row in rows], dtype=np.float64)
    target_times = np.linspace(start_time, end_time, model_timesteps, dtype=np.float64)
    resampled = []

    for target_index, target_time in enumerate(target_times):
        reading = {}

        for feature in FEATURE_KEYS:
            source_values = np.asarray([row[feature] for row in rows], dtype=np.float64)
            reading[feature] = float(np.interp(target_time, source_times, source_values))

        reading["t_relative"] = float(target_index / max(model_timesteps - 1, 1) * window_seconds)
        resampled.append(reading)

    return resampled


def flatten_window(window_record):
    windows_by_node = window_record["windows_by_node"]
    rows = []

    for timestep in range(MODEL_TIMESTEPS):
        row = []

        for node_id in NODE_ORDER:
            node_rows = windows_by_node[str(node_id)]
            reading = node_rows[timestep]
            row.extend(float(reading[feature]) for feature in FEATURE_KEYS)

        rows.append(row)

    return np.asarray(rows, dtype=np.float32)


def validate_window_record(record):
    windows_by_node = record.get("windows_by_node")

    if not isinstance(windows_by_node, dict):
        raise ValueError("window record is missing windows_by_node")

    for node_id in NODE_ORDER:
        node_rows = windows_by_node.get(str(node_id))

        if not isinstance(node_rows, list) or len(node_rows) != MODEL_TIMESTEPS:
            raise ValueError(f"node {node_id} must contain {MODEL_TIMESTEPS} readings")

        for reading in node_rows:
            for feature in FEATURE_KEYS:
                safe_float(reading[feature])


def load_window_records(windows_path):
    records = []

    for record in iter_jsonl(windows_path):
        validate_window_record(record)
        records.append(record)

    return records


def records_to_arrays(records):
    if not records:
        raise ValueError("no window records found")

    x_values = np.stack([flatten_window(record) for record in records], axis=0)
    y_values = np.asarray([str(record["activity"]) for record in records])

    if not np.isfinite(x_values).all():
        raise ValueError("window dataset contains NaN or inf values")

    return x_values, y_values


def summarize_window_records(records, window_seconds=WINDOW_SECONDS, model_timesteps=MODEL_TIMESTEPS):
    class_counts = Counter(str(record["activity"]) for record in records)
    participants = sorted({str(record.get("participant_id", "unknown")) for record in records})
    sessions = sorted({str(record.get("session_id", "unknown")) for record in records})

    return {
        "generated_at": utc_now_iso(),
        "total_windows": len(records),
        "classes": dict(sorted(class_counts.items())),
        "participants": participants,
        "sessions": sessions,
        "session_count": len(sessions),
        "window_seconds": float(window_seconds),
        "model_timesteps": int(model_timesteps),
        "node_order": list(NODE_ORDER),
        "features_per_node": list(FEATURE_KEYS),
        "features": len(NODE_ORDER) * len(FEATURE_KEYS),
    }


def split_ids_from_records(records, split_by="session", seed=42, train_ratio=0.7, val_ratio=0.15):
    if split_by not in ("session", "participant"):
        raise ValueError("split_by must be 'session' or 'participant'")

    key_name = "participant_id" if split_by == "participant" else "session_id"
    ids = sorted({str(record.get(key_name, "unknown")) for record in records})

    if split_by == "participant" and len(ids) < 3:
        split_by = "session"
        key_name = "session_id"
        ids = sorted({str(record.get(key_name, "unknown")) for record in records})

    rng = random.Random(seed)
    rng.shuffle(ids)
    n_ids = len(ids)

    if n_ids == 0:
        return split_by, {"train": [], "val": [], "test": []}

    if n_ids == 1:
        return split_by, {"train": ids, "val": [], "test": []}

    train_count = max(1, int(round(n_ids * train_ratio)))
    val_count = int(round(n_ids * val_ratio))

    if train_count >= n_ids:
        train_count = n_ids - 1

    remaining = n_ids - train_count

    if remaining > 1 and val_count == 0:
        val_count = 1

    if val_count >= remaining:
        val_count = remaining - 1

    train_ids = sorted(ids[:train_count])
    val_ids = sorted(ids[train_count:train_count + val_count])
    test_ids = sorted(ids[train_count + val_count:])

    return split_by, {
        "train": train_ids,
        "val": val_ids,
        "test": test_ids,
    }


def filter_records_by_split(records, split_ids, split_by):
    key_name = "participant_id" if split_by == "participant" else "session_id"
    split_id_set = {str(item) for item in split_ids}
    return [
        record
        for record in records
        if str(record.get(key_name, "unknown")) in split_id_set
    ]


def load_split_files(split_dir):
    summary_path = os.path.join(split_dir, "split_summary.json")
    summary = read_json(summary_path, default={}) or {}
    split_by = summary.get("split_by", "session")
    splits = {}

    for split_name in ("train", "val", "test"):
        path = os.path.join(split_dir, f"{split_name}_ids.json")
        splits[split_name] = read_json(path, default=[]) or []

    return split_by, splits


def class_counts_for_records(records):
    counts = defaultdict(int)

    for record in records:
        counts[str(record["activity"])] += 1

    return dict(sorted(counts.items()))
