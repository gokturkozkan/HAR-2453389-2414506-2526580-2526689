#!/usr/bin/env python3
import argparse
import os

from har_dataset_utils import (
    FEATURE_KEYS,
    MODEL_TIMESTEPS,
    NODE_ORDER,
    WINDOW_SECONDS,
    append_jsonl,
    class_counts_for_records,
    default_dataset_root,
    ensure_dir,
    group_samples_by_node,
    iter_jsonl,
    load_raw_sessions,
    resample_node,
    split_ids_from_records,
    summarize_window_records,
    write_json,
)


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Build 200x27 HAR windows from raw session JSONL files.")
    parser.add_argument("--dataset-root", default=default_dataset_root())
    parser.add_argument("--window-seconds", type=float, default=WINDOW_SECONDS)
    parser.add_argument("--timesteps", type=int, default=MODEL_TIMESTEPS)
    parser.add_argument("--stride-seconds", type=float, default=3.0)
    parser.add_argument("--split-by", choices=("participant", "session"), default="participant")
    parser.add_argument("--seed", type=int, default=42)
    return parser


def build_windows_for_session(session, args, running_index):
    metadata = session["metadata"]
    samples = list(iter_jsonl(session["samples_path"]))
    grouped = group_samples_by_node(samples)

    if any(len(grouped[node_id]) < 2 for node_id in NODE_ORDER):
        return [], {
            "session_id": metadata.get("session_id"),
            "status": "skipped",
            "reason": "not enough samples for all nodes",
            "sample_counts": {str(node_id): len(grouped[node_id]) for node_id in NODE_ORDER},
        }

    common_start = max(grouped[node_id][0]["t_host"] for node_id in NODE_ORDER)
    common_end = min(grouped[node_id][-1]["t_host"] for node_id in NODE_ORDER)
    latest_start = common_end - args.window_seconds

    if latest_start < common_start:
        return [], {
            "session_id": metadata.get("session_id"),
            "status": "skipped",
            "reason": "common time range shorter than one window",
            "common_seconds": round(common_end - common_start, 3),
            "sample_counts": {str(node_id): len(grouped[node_id]) for node_id in NODE_ORDER},
        }

    records = []
    window_index = 0
    start_time = common_start

    while start_time <= latest_start + 1e-6:
        windows_by_node = {}
        valid = True

        for node_id in NODE_ORDER:
            resampled = resample_node(
                grouped[node_id],
                start_time,
                window_seconds=args.window_seconds,
                model_timesteps=args.timesteps,
            )

            if resampled is None:
                valid = False
                break

            windows_by_node[str(node_id)] = [
                {feature: float(reading[feature]) for feature in FEATURE_KEYS}
                for reading in resampled
            ]

        if valid:
            sample_id = (
                f"{metadata.get('participant_id', 'unknown')}_"
                f"{metadata.get('activity', 'unknown')}_{running_index + len(records):06d}"
            )
            records.append({
                "sample_id": sample_id,
                "session_id": metadata.get("session_id"),
                "participant_id": metadata.get("participant_id"),
                "activity": metadata.get("activity"),
                "window_index": window_index,
                "window_start_host": float(start_time),
                "window_end_host": float(start_time + args.window_seconds),
                "window_seconds": float(args.window_seconds),
                "model_timesteps": int(args.timesteps),
                "node_order": list(NODE_ORDER),
                "features_per_node": list(FEATURE_KEYS),
                "windows_by_node": windows_by_node,
            })

        window_index += 1
        start_time += args.stride_seconds

    return records, {
        "session_id": metadata.get("session_id"),
        "status": "ok",
        "windows": len(records),
        "common_seconds": round(common_end - common_start, 3),
        "sample_counts": {str(node_id): len(grouped[node_id]) for node_id in NODE_ORDER},
    }


def main():
    args = build_arg_parser().parse_args()
    processed_dir = ensure_dir(os.path.join(args.dataset_root, "processed"))
    split_dir = ensure_dir(os.path.join(args.dataset_root, "splits"))
    windows_path = os.path.join(processed_dir, "windows_200x27.jsonl")
    summary_path = os.path.join(processed_dir, "dataset_summary.json")
    sessions = load_raw_sessions(args.dataset_root)

    if not sessions:
        raise SystemExit(f"No raw sessions found under {os.path.join(args.dataset_root, 'raw_sessions')}")

    all_records = []
    session_summaries = []

    with open(windows_path, "w", encoding="utf-8") as output_file:
        for session in sessions:
            records, session_summary = build_windows_for_session(session, args, len(all_records))
            session_summaries.append(session_summary)

            for record in records:
                append_jsonl(output_file, record)

            all_records.extend(records)

    split_by, splits = split_ids_from_records(all_records, split_by=args.split_by, seed=args.seed)

    for split_name, ids in splits.items():
        write_json(os.path.join(split_dir, f"{split_name}_ids.json"), ids)

    split_summary = {
        "split_by": split_by,
        "seed": args.seed,
        "splits": splits,
    }
    write_json(os.path.join(split_dir, "split_summary.json"), split_summary)

    summary = summarize_window_records(
        all_records,
        window_seconds=args.window_seconds,
        model_timesteps=args.timesteps,
    )
    summary["stride_seconds"] = float(args.stride_seconds)
    summary["class_counts"] = class_counts_for_records(all_records)
    summary["session_summaries"] = session_summaries
    summary["split"] = split_summary
    write_json(summary_path, summary)

    print(f"Sessions read: {len(sessions)}")
    print(f"Windows written: {len(all_records)}")
    print(f"Output: {windows_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
