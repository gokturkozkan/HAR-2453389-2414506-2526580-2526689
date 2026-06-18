#!/usr/bin/env python3
import argparse
import json
import os

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder, StandardScaler

from har_dataset_utils import (
    default_dataset_root,
    ensure_dir,
    filter_records_by_split,
    load_split_files,
    load_window_records,
    records_to_arrays,
    utc_now_iso,
    write_json,
)


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Train the own HAR model on 200x27 window data.")
    parser.add_argument(
        "--windows-path",
        default=os.path.join(default_dataset_root(), "processed", "windows_200x27.jsonl"),
    )
    parser.add_argument("--split-dir", default=os.path.join(default_dataset_root(), "splits"))
    parser.add_argument("--model-dir", default=os.path.join(os.path.dirname(__file__), "model"))
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--patience", type=int, default=8)
    return parser


def make_model(num_classes, learning_rate):
    import tensorflow as tf

    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(200, 27)),
        tf.keras.layers.Conv1D(64, 5, activation="relu", padding="same"),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.MaxPooling1D(pool_size=2),
        tf.keras.layers.Conv1D(128, 5, activation="relu", padding="same"),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.MaxPooling1D(pool_size=2),
        tf.keras.layers.LSTM(128),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(64, activation="relu"),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(num_classes, activation="softmax"),
    ])
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def split_records(records, split_dir):
    if not os.path.isdir(split_dir):
        return records, [], [], "none"

    split_by, splits = load_split_files(split_dir)
    train_records = filter_records_by_split(records, splits.get("train", []), split_by)
    val_records = filter_records_by_split(records, splits.get("val", []), split_by)
    test_records = filter_records_by_split(records, splits.get("test", []), split_by)

    if not train_records:
        return records, [], [], "none"

    return train_records, val_records, test_records, split_by


def scale_arrays(x_train, x_val, x_test):
    scaler = StandardScaler()
    scaler.fit(x_train.reshape(-1, x_train.shape[-1]))

    def transform(array):
        if array is None or len(array) == 0:
            return array

        return scaler.transform(array.reshape(-1, array.shape[-1])).reshape(array.shape)

    return scaler, transform(x_train), transform(x_val), transform(x_test)


def evaluate_predictions(label_encoder, y_true, probabilities):
    if probabilities is None or len(probabilities) == 0:
        return None

    y_pred_idx = np.argmax(probabilities, axis=1)
    y_pred = label_encoder.inverse_transform(y_pred_idx)
    labels = [str(label) for label in label_encoder.classes_]

    return {
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
    }


def main():
    args = build_arg_parser().parse_args()
    records = load_window_records(args.windows_path)
    train_records, val_records, test_records, split_by = split_records(records, args.split_dir)

    if len(train_records) < 4:
        raise SystemExit("Need at least 4 training windows before training a model.")

    x_train, y_train_labels = records_to_arrays(train_records)
    x_val, y_val_labels = records_to_arrays(val_records) if val_records else (np.empty((0, 200, 27)), np.asarray([]))
    x_test, y_test_labels = records_to_arrays(test_records) if test_records else (np.empty((0, 200, 27)), np.asarray([]))

    label_encoder = LabelEncoder()
    label_encoder.fit(np.asarray([str(record["activity"]) for record in records]))
    y_train = label_encoder.transform(y_train_labels)
    y_val = label_encoder.transform(y_val_labels) if len(y_val_labels) else np.asarray([])

    scaler, x_train_scaled, x_val_scaled, x_test_scaled = scale_arrays(x_train, x_val, x_test)
    model = make_model(len(label_encoder.classes_), args.learning_rate)

    callbacks = []

    if len(x_val_scaled):
        import tensorflow as tf

        callbacks.append(
            tf.keras.callbacks.EarlyStopping(
                monitor="val_loss",
                patience=args.patience,
                restore_best_weights=True,
            )
        )

    history = model.fit(
        x_train_scaled,
        y_train,
        validation_data=(x_val_scaled, y_val) if len(x_val_scaled) else None,
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=callbacks,
        verbose=1,
    )

    ensure_dir(args.model_dir)
    model_path = os.path.join(args.model_dir, "own_har_200x27_model.keras")
    scaler_path = os.path.join(args.model_dir, "own_har_200x27_scaler.pkl")
    label_encoder_path = os.path.join(args.model_dir, "own_har_200x27_label_encoder.pkl")
    metrics_path = os.path.join(args.model_dir, "own_har_200x27_metrics.json")

    model.save(model_path)
    joblib.dump(scaler, scaler_path)
    joblib.dump(label_encoder, label_encoder_path)

    train_probs = model.predict(x_train_scaled, verbose=0)
    val_probs = model.predict(x_val_scaled, verbose=0) if len(x_val_scaled) else None
    test_probs = model.predict(x_test_scaled, verbose=0) if len(x_test_scaled) else None

    metrics = {
        "generated_at": utc_now_iso(),
        "model_profile": "own_har_200x27",
        "input_shape": [200, 27],
        "split_by": split_by,
        "sample_counts": {
            "train": int(len(train_records)),
            "val": int(len(val_records)),
            "test": int(len(test_records)),
        },
        "classes": [str(label) for label in label_encoder.classes_],
        "history": {
            key: [float(value) for value in values]
            for key, values in history.history.items()
        },
        "train": evaluate_predictions(label_encoder, y_train_labels, train_probs),
        "val": evaluate_predictions(label_encoder, y_val_labels, val_probs),
        "test": evaluate_predictions(label_encoder, y_test_labels, test_probs),
        "files": {
            "model": model_path,
            "scaler": scaler_path,
            "label_encoder": label_encoder_path,
        },
    }
    write_json(metrics_path, metrics)

    print(f"Saved model: {model_path}")
    print(f"Saved scaler: {scaler_path}")
    print(f"Saved label encoder: {label_encoder_path}")
    print(f"Saved metrics: {metrics_path}")

    if metrics["test"]:
        print("Test accuracy:", metrics["test"]["accuracy"])
    elif metrics["val"]:
        print("Validation accuracy:", metrics["val"]["accuracy"])


if __name__ == "__main__":
    main()
