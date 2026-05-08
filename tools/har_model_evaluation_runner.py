"""Evaluate the HAR model on a labeled CSV file.

Expected CSV columns:
  ax, ay, az, gx, gy, gz, label

Rows are split into non-overlapping 32-sample windows. A window is evaluated
only when all rows in that window have the same label.

Example:
  python tools/har_model_evaluation_runner.py --csv Reports/evidence/labeled_windows.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "Hardware" / "RaspberryPi" / "HAR-backend"
DEFAULT_OUT = REPO / "Reports" / "evidence" / "har_model_evaluation.json"
FEATURES = ("ax", "ay", "az", "gx", "gy", "gz")
WINDOW_SIZE = 32


def load_backend_model():
    sys.path.insert(0, str(BACKEND))
    from routes.activity import load_model, predict_activity

    load_model()
    return predict_activity


def read_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [col for col in [*FEATURES, "label"] if col not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"CSV is missing required columns: {', '.join(missing)}")
        for row in reader:
            rows.append(row)
    return rows


def make_windows(rows: list[dict]) -> list[tuple[str, list[dict[str, float]]]]:
    windows = []
    for start in range(0, len(rows) - WINDOW_SIZE + 1, WINDOW_SIZE):
        chunk = rows[start : start + WINDOW_SIZE]
        labels = {r["label"].strip() for r in chunk}
        if len(labels) != 1:
            continue
        label = labels.pop()
        readings = []
        for row in chunk:
            readings.append({feature: float(row[feature]) for feature in FEATURES})
        windows.append((label, readings))
    return windows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Labeled CSV with ax, ay, az, gx, gy, gz, label columns.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    rows = read_rows(Path(args.csv))
    windows = make_windows(rows)
    if not windows:
        raise SystemExit("No valid single-label 32-sample windows found.")

    predict_activity = load_backend_model()
    confusion: dict[str, Counter] = defaultdict(Counter)
    details = []

    for expected, readings in windows:
        predicted, confidence = predict_activity(readings)
        confusion[expected][predicted] += 1
        details.append(
            {
                "expected": expected,
                "predicted": predicted,
                "confidence": confidence,
                "passed": expected == predicted,
            }
        )

    total = len(details)
    correct = sum(1 for item in details if item["passed"])
    labels = sorted(set(confusion.keys()) | {item["predicted"] for item in details})
    per_class = {}
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in labels if other != label)
        fn = sum(confusion[label][other] for other in labels if other != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(confusion[label].values()),
        }

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "csv": str(Path(args.csv).resolve()),
        "window_size": WINDOW_SIZE,
        "total_windows": total,
        "accuracy": round(correct / total, 4),
        "confusion_matrix": {label: dict(confusion[label]) for label in labels},
        "per_class": per_class,
        "details": details,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Accuracy: {evidence['accuracy']} ({correct}/{total})")


if __name__ == "__main__":
    main()
