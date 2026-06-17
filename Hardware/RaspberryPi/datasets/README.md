# HAR Dataset Rebuild Notes

`processed/windows_200x27.jsonl` is intentionally not committed to Git.
It is a generated file and is currently too large for normal GitHub pushes
because GitHub rejects single files over 100 MB.

The raw session data is committed under `raw_sessions/`, so another machine can
recreate the processed window file from source.

## Rebuild On Another Machine

From the repository root:

```bash
git checkout server-fixing-pi
pip install numpy

python3 Hardware/RaspberryPi/build_window_dataset.py \
  --dataset-root Hardware/RaspberryPi/datasets \
  --split-by session \
  --seed 42 \
  --stride-seconds 3.0 \
  --window-seconds 6.0 \
  --timesteps 200
```

This creates or overwrites:

```text
Hardware/RaspberryPi/datasets/processed/windows_200x27.jsonl
Hardware/RaspberryPi/datasets/processed/dataset_summary.json
Hardware/RaspberryPi/datasets/splits/train_ids.json
Hardware/RaspberryPi/datasets/splits/val_ids.json
Hardware/RaspberryPi/datasets/splits/test_ids.json
Hardware/RaspberryPi/datasets/splits/split_summary.json
```

## Why This File Is Missing After Clone

If `processed/windows_200x27.jsonl` is missing after cloning, that is expected.
It was removed from Git tracking to keep pushes working without Git LFS. The
local copy on the original machine was not deleted; only the Git-tracked copy
was removed.

## For Codex Or Future Developers

When code expects `Hardware/RaspberryPi/datasets/processed/windows_200x27.jsonl`
and the file is missing, run the rebuild command above before training or
evaluation. Do not try to recommit this file with normal Git unless Git LFS is
installed and configured for it.
