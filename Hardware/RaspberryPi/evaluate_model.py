#!/usr/bin/env python3
import argparse
import os

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from har_dataset_utils import (
    default_dataset_root,
    filter_records_by_split,
    load_split_files,
    load_window_records,
    records_to_arrays,
    utc_now_iso,
    write_json,
)


def build_arg_parser():
    model_dir = os.path.join(os.path.dirname(__file__), "model")
    parser = argparse.ArgumentParser(description="Evaluate a saved HAR model on processed windows.")
    parser.add_argument(
        "--windows-path",
        default=os.path.join(default_dataset_root(), "processed", "windows_200x27.jsonl"),
    )
    parser.add_argument("--split-dir", default=os.path.join(default_dataset_root(), "splits"))
    parser.add_argument("--model-path", default=os.path.join(model_dir, "own_har_200x27_model.keras"))
    parser.add_argument("--scaler-path", default=os.path.join(model_dir, "own_har_200x27_scaler.pkl"))
    parser.add_argument("--label-encoder-path", default=os.path.join(model_dir, "own_har_200x27_label_encoder.pkl"))
    parser.add_argument("--output-path", default=os.path.join(model_dir, "own_har_200x27_evaluation.json"))
    parser.add_argument("--split", choices=("train", "val", "test", "all"), default="test")
    return parser


def select_records(records, split_dir, split_name):
    if split_name == "all" or not os.path.isdir(split_dir):
        return records, "all"

    split_by, splits = load_split_files(split_dir)
    selected = filter_records_by_split(records, splits.get(split_name, []), split_by)

    if not selected:
        return records, "all"

    return selected, f"{split_name}:{split_by}"


def main():
    args = build_arg_parser().parse_args()

    import tensorflow as tf

    records = load_window_records(args.windows_path)
    selected_records, evaluated_split = select_records(records, args.split_dir, args.split)
    x_values, y_true = records_to_arrays(selected_records)
    scaler = joblib.load(args.scaler_path)
    label_encoder = joblib.load(args.label_encoder_path)
    model = tf.keras.models.load_model(args.model_path)

    x_scaled = scaler.transform(x_values.reshape(-1, x_values.shape[-1])).reshape(x_values.shape)
    probabilities = model.predict(x_scaled, verbose=0)
    y_pred_idx = np.argmax(probabilities, axis=1)
    y_pred = label_encoder.inverse_transform(y_pred_idx)
    labels = [str(label) for label in label_encoder.classes_]

    report = {
        "generated_at": utc_now_iso(),
        "model_profile": "own_har_200x27",
        "evaluated_split": evaluated_split,
        "sample_count": int(len(selected_records)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "classification_report": classification_report(
            y_true,
            y_pred,
            labels=labels,
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "labels": labels,
        "files": {
            "model": args.model_path,
            "scaler": args.scaler_path,
            "label_encoder": args.label_encoder_path,
            "windows": args.windows_path,
        },
    }
    write_json(args.output_path, report)

    print(f"Evaluated split: {evaluated_split}")
    print(f"Samples: {len(selected_records)}")
    print(f"Accuracy: {report['accuracy']:.4f}")
    print(f"Saved report: {args.output_path}")
    print("Confusion matrix labels:", labels)
    print(np.asarray(report["confusion_matrix"]))


if __name__ == "__main__":
    main()
