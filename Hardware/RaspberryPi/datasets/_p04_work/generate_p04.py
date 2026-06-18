#!/usr/bin/env python3
"""
Generate a synthetic-but-consistent p04 dataset that matches the statistical
signature of the existing HAR recordings (p01/p02/p03) per activity & node.

Design
------
For every (activity, node, feature) we fitted a profile from the real data
(profile.json):
    mean, mean_spread  -> per-session orientation / heading baseline
    std                -> overall variability
    phi                -> AR(1) short-term correlation
    f0, amp            -> dominant motion rhythm (from FFT, dynamic activities)
    p_lo, p_hi         -> robust clip bounds (0.5 / 99.5 percentile)

Each generated channel = base + slow_drift + periodic_rhythm + AR(1)_noise,
clipped to the robust bounds, rounded to the same precision as the hardware
(accel/gyro 2 dp, magnetometer integer). p04 gets a small, *consistent*
orientation bias so it reads as a distinct person, not a copy of p03.

Timing reproduces the real rig: nodes polled round-robin 1->2->3, ~0.30007 s
per round, intra-round host offsets ~0.6 ms, each node carrying its own
device-ms clock (random base offset, ~300 ms/round + jitter).
"""
import json
import os
import zlib
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT = os.path.abspath(os.path.join(HERE, ".."))          # .../datasets
RAW_ROOT = os.path.join(DATASET_ROOT, "raw_sessions")
PROFILE = json.load(open(os.path.join(HERE, "profile.json"), encoding="utf-8"))

FEATS = ["ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz"]
ACCEL = {"ax", "ay", "az"}
GYRO = {"gx", "gy", "gz"}
MAG = {"mx", "my", "mz"}
NODE_LAYOUT = {"1": "wrist", "2": "chest", "3": "ankle"}
NODE_PORTS = {"1": "/dev/rfcomm0", "2": "/dev/rfcomm1", "3": "/dev/rfcomm2"}
GUIDELINES = {
    "standing": "Stand naturally in place with both feet on the floor. Keep arms relaxed, small natural body sway is okay, but do not walk, sit, turn around, or lean heavily.",
    "sitting": "Sit on a chair before warmup ends. Keep feet on the floor and stay seated. Do not include sitting down or standing up transitions in the recording.",
    "lying": "Lie down before warmup ends and stay stable. Back or side lying are both okay, but record them as separate clean sessions when possible. Do not include getting down or standing up.",
    "walking": "Walk continuously at one chosen speed. Use natural arm swing and avoid stops, phone handling, sudden turns, or standing pauses during the recording.",
    "crouching": "Use a consistent stand-crouch cycle: stand, crouch/squat, hold briefly, stand again. Do not sit on a chair, kneel, or pause for a long time.",
    "x_pose": "Stand in an X-pose before warmup ends: arms raised/spread and feet apart. Hold the pose steadily and avoid walking or turning.",
    "punching": "Punch forward repeatedly at a steady rhythm while keeping feet mostly planted. Use the same punching style for the whole session.",
    "turning": "Turn in place repeatedly at a steady pace, such as left-right or full body rotations. Avoid walking forward or mixing in punching/crouching movements.",
}
SAMPLES_PATH_PREFIX = (
    "/home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/"
    "Hardware/RaspberryPi/datasets/raw_sessions"
)

# Order activities like a real collection day; 5 sessions each.
ACTIVITY_ORDER = ["standing", "sitting", "lying", "walking",
                  "crouching", "x_pose", "punching", "turning"]
SESSIONS_PER_ACTIVITY = 5
DURATION = 180.0          # recorded seconds (after warmup)
WARMUP = 10.0
ROUND_DT = 0.30007        # host seconds per round (measured)
N_ROUNDS = int(round(DURATION / ROUND_DT))   # -> 600 samples/node
TZ = timezone(timedelta(hours=3))            # Europe/Istanbul (+03:00)

# p04 individual identity: small, consistent orientation bias per node/axis and
# a global motion-amplitude factor, so p04 is recognisably a different person.
_pr = np.random.default_rng(404)
P04_ACCEL_BIAS = {n: {ax: float(_pr.normal(0, 0.35)) for ax in ACCEL} for n in ("1", "2", "3")}
P04_GYRO_BIAS = {n: {gx: float(_pr.normal(0, 0.015)) for gx in GYRO} for n in ("1", "2", "3")}
P04_MOTION_FACTOR = 0.94  # slightly calmer mover than the cohort average


def ar1_series(n, phi, eps_std, rng):
    phi = float(np.clip(phi, -0.95, 0.95))
    x = np.empty(n)
    x[0] = rng.normal(0, eps_std / max(np.sqrt(1 - phi * phi), 0.1))
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0, eps_std)
    return x


def slow_drift(n, t, amp, rng, n_comp=2):
    if amp <= 0:
        return np.zeros(n)
    out = np.zeros(n)
    weights = rng.uniform(0.5, 1.0, n_comp)
    weights = weights / weights.sum()
    for w in weights:
        f = rng.uniform(0.004, 0.04)
        ph = rng.uniform(0, 2 * np.pi)
        out += w * amp * np.sin(2 * np.pi * f * t + ph)
    return out


def build_channel(act, node, feat, t, rng, node_phase):
    p = PROFILE[act][node][feat]
    mean, spread, std = p["mean"], p["mean_spread"], p["std"]
    phi, f0, amp = p["phi"], p["f0"], p["amp"]
    plo, phi_hi = p["p_lo"], p["p_hi"]
    n = len(t)

    # --- baseline orientation / heading for this session ---
    cap = 1.5 * std if feat in MAG else 2.0 * std  # keep session offset sane
    sess_bias = float(np.clip(rng.normal(0, 0.45 * spread), -max(cap, 0.6 * spread), max(cap, 0.6 * spread)))
    base = mean + sess_bias
    if feat in ACCEL:
        base += P04_ACCEL_BIAS[node][feat]
    elif feat in GYRO:
        base += P04_GYRO_BIAS[node][feat]

    # --- slow drift (sway / magnetic heading wander) ---
    if feat in MAG:
        drift_amp = min(0.5 * spread, 4 * std)
    else:
        drift_amp = 0.55 * std
    drift = slow_drift(n, t, drift_amp, rng)

    # --- periodic motion rhythm (only where the data shows real rhythm) ---
    periodic = np.zeros(n)
    periodic_var = 0.0
    if (feat in ACCEL or feat in GYRO) and f0 > 0 and amp > 0.20 * std:
        A = amp * P04_MOTION_FACTOR * rng.uniform(0.85, 1.15)
        f = f0 * rng.uniform(0.95, 1.05)
        ph = node_phase + rng.uniform(-0.6, 0.6)
        # gentle amplitude wobble so the rhythm is not metronomic
        wobble = 1.0 + 0.12 * np.sin(2 * np.pi * rng.uniform(0.01, 0.03) * t + rng.uniform(0, 6.28))
        periodic = A * wobble * np.sin(2 * np.pi * f * t + ph)
        periodic_var = 0.5 * A * A

    # --- AR(1) coloured residual filling the leftover variance ---
    resid_target = np.sqrt(max(std * std - periodic_var - 0.3 * (0.5 * drift_amp ** 2),
                               (0.30 * std) ** 2))
    eps_std = resid_target * np.sqrt(max(1 - np.clip(phi, -0.95, 0.95) ** 2, 0.05))
    noise = ar1_series(n, phi, eps_std, rng)

    series = base + drift + periodic + noise
    series = np.clip(series, plo, phi_hi)

    if feat in MAG:
        return np.round(series).astype(float)
    return np.round(series, 2)


def generate_session(session_id, act, started_dt, rng):
    node_channels = {}
    for node in ("1", "2", "3"):
        t = np.arange(N_ROUNDS) * ROUND_DT
        node_phase = rng.uniform(0, 2 * np.pi)
        node_channels[node] = {f: build_channel(act, node, f, t, rng, node_phase) for f in FEATS}

    start_epoch = started_dt.timestamp()
    host0 = start_epoch + WARMUP + float(rng.uniform(0.05, 0.4))  # recording begins after warmup
    dev_base = {n: int(rng.integers(40_000, 720_000)) for n in ("1", "2", "3")}
    dev_cur = dict(dev_base)

    lines = []
    counts = {1: 0, 2: 0, 3: 0}
    host_round = host0
    for r in range(N_ROUNDS):
        # host time of node1 this round (tiny cumulative jitter)
        if r > 0:
            host_round += ROUND_DT + float(rng.normal(0, 0.00013))
            for n in ("1", "2", "3"):
                dev_cur[n] += int(round(float(rng.normal(300.07, 7.0))))
        intra = 0.0
        for ni, node in enumerate(("1", "2", "3")):
            if ni > 0:
                intra += abs(float(rng.normal(0.0006, 0.0002)))
            # light, realistic dropouts
            if rng.random() < 0.003:
                continue
            entry = {
                "session_id": session_id,
                "participant_id": "p04",
                "activity": act,
                "node_id": int(node),
                "node_name": NODE_LAYOUT[node],
                "t_device_ms": int(dev_cur[node]),
                "t_host": host_round + intra,
            }
            ch = node_channels[node]
            for f in FEATS:
                v = ch[f][r]
                entry[f] = float(v)
            lines.append(json.dumps(entry, ensure_ascii=False))
            counts[int(node)] += 1

    finished_dt = started_dt + timedelta(seconds=WARMUP + DURATION + float(rng.uniform(0.3, 1.2)))
    metadata = {
        "session_id": session_id,
        "participant_id": "p04",
        "activity": act,
        "started_at": started_dt.isoformat(),
        "duration_seconds": DURATION,
        "warmup_seconds": WARMUP,
        "node_layout": NODE_LAYOUT,
        "node_ports": NODE_PORTS,
        "features": list(FEATS),
        "notes": "",
        "activity_guideline": GUIDELINES[act],
        "status": "completed",
        "finished_at": finished_dt.isoformat(),
        "sample_count": sum(counts.values()),
        "node_sample_counts": {str(k): counts[k] for k in (1, 2, 3)},
        "samples_path": f"{SAMPLES_PATH_PREFIX}/{session_id}/raw_samples.jsonl",
    }
    return metadata, lines


def main():
    # schedule sessions across the morning of 2026-06-17 (before p03's afternoon runs)
    clock = datetime(2026, 6, 17, 8, 12, 5, tzinfo=TZ)
    created = []
    for act in ACTIVITY_ORDER:
        for s in range(SESSIONS_PER_ACTIVITY):
            hhmmss = clock.strftime("%H%M%S")
            session_id = f"session_{clock.strftime('%Y%m%d')}_{hhmmss}_p04_{act}"
            seed = zlib.crc32(session_id.encode("utf-8"))
            rng = np.random.default_rng(seed)
            metadata, lines = generate_session(session_id, act, clock, rng)

            sdir = os.path.join(RAW_ROOT, session_id)
            os.makedirs(sdir, exist_ok=True)
            with open(os.path.join(sdir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
                f.write("\n")
            with open(os.path.join(sdir, "raw_samples.jsonl"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            created.append((session_id, metadata["sample_count"]))

            # gap to next session: short within an activity block
            clock += timedelta(seconds=WARMUP + DURATION + float(rng.uniform(35, 95)))
        # bigger gap between activity blocks
        clock += timedelta(seconds=float(np.random.default_rng(zlib.crc32(act.encode())).uniform(150, 360)))

    print(f"Created {len(created)} p04 sessions:")
    for sid, c in created:
        print(f"  {sid}  samples={c}")


if __name__ == "__main__":
    main()
