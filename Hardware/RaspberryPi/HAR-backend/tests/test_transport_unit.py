import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if "serial" not in sys.modules:
    sys.modules["serial"] = types.SimpleNamespace(
        SerialException=Exception,
        Serial=lambda *args, **kwargs: None,
    )

import tdma_hub


def sample(node_id=1):
    return {
        "node_id": node_id,
        "t": 100,
        "ax": 1.0,
        "ay": 2.0,
        "az": 3.0,
        "gx": 0.1,
        "gy": 0.2,
        "gz": 0.3,
        "mx": 10.0,
        "my": 20.0,
        "mz": 30.0,
    }


def fused_timestep():
    return {
        "nodes": {
            "1": {key: float(value) for key, value in sample(1).items() if key in tdma_hub.FEATURE_KEYS},
            "2": {key: float(value) for key, value in sample(2).items() if key in tdma_hub.FEATURE_KEYS},
            "3": {key: float(value) for key, value in sample(3).items() if key in tdma_hub.FEATURE_KEYS},
        }
    }


def test_parse_frame_accepts_full_and_legacy_sensor_formats():
    full = tdma_hub.parse_frame("1,123,1.1,2.2,3.3,0.1,0.2,0.3,10,20,30")
    assert full == {
        "node_id": 1,
        "t": 123,
        "ax": 1.1,
        "ay": 2.2,
        "az": 3.3,
        "gx": 0.1,
        "gy": 0.2,
        "gz": 0.3,
        "mx": 10.0,
        "my": 20.0,
        "mz": 30.0,
    }

    legacy = tdma_hub.parse_frame("2,124,1,2,3,4,5,6")
    assert legacy["node_id"] == 2
    assert legacy["mx"] == 0.0
    assert legacy["my"] == 0.0
    assert legacy["mz"] == 0.0


def test_parse_frame_rejects_short_bad_or_unknown_node_lines():
    assert tdma_hub.parse_frame("1,123,1") is None
    assert tdma_hub.parse_frame("99,123,1,2,3,4,5,6") is None
    assert tdma_hub.parse_frame("not,csv,data") is None


def test_axis_node_order_and_mag_mode_parsers_are_stable():
    assert tdma_hub.parse_node_order("3,2,1") == (3, 2, 1)
    assert tdma_hub.parse_node_order("1,1,3") == (1, 2, 3)
    assert tdma_hub.parse_axis_transform("+z-y-x") == "+z-y-x"
    assert tdma_hub.parse_axis_transform("bad") == "+x+y+z"
    assert tdma_hub.parse_mag_mode("divide100") == "div100"
    assert tdma_hub.parse_mag_mode("invalid") == "raw"

    node_axes = tdma_hub.parse_node_axis_transforms("1:+x+y+z;2:+z-y-x;3:-x+y+z")
    assert node_axes == {
        1: "+x+y+z",
        2: "+z-y-x",
        3: "-x+y+z",
    }


def test_build_fused_timestep_uses_latest_samples_for_all_nodes():
    latest = {
        1: sample(1),
        2: sample(2),
        3: sample(3),
    }

    timestep = tdma_hub.build_fused_timestep((1, 2, 3), latest)

    assert sorted(timestep["nodes"]) == ["1", "2", "3"]
    assert timestep["nodes"]["1"]["ax"] == 1.0
    assert timestep["nodes"]["2"]["mz"] == 30.0


def test_build_predict_payload_rejects_short_windows_and_accepts_full_windows():
    short_id, short_payload, short_error = tdma_hub.build_predict_payload([fused_timestep()])

    assert short_id.startswith("tdma-")
    assert short_payload is None
    assert "expected 200" in short_error

    window = [fused_timestep() for _ in range(tdma_hub.WINDOW_SIZE)]
    prediction_id, payload, error = tdma_hub.build_predict_payload(
        window,
        node_order=(3, 2, 1),
        axis_transform="-x-z+y",
        mag_mode="center",
    )

    assert prediction_id.startswith("tdma-")
    assert error is None
    assert payload["node_order"] == [3, 2, 1]
    assert payload["axis_transform"] == "-x-z+y"
    assert payload["mag_mode"] == "center"
    assert len(payload["windows_by_node"]["1"]) == tdma_hub.WINDOW_SIZE
    assert payload["windows_by_node"]["1"][0]["ax"] == 1.0


def test_backoff_is_exponential_and_capped():
    assert tdma_hub.compute_backoff(0) == tdma_hub.BACKOFF_BASE
    assert tdma_hub.compute_backoff(2) == tdma_hub.BACKOFF_BASE * 4
    assert tdma_hub.compute_backoff(100) == tdma_hub.BACKOFF_MAX
