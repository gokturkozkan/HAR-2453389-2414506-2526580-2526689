import pytest

from tdma_test_helpers import make_samples
from tdma_wifi_transport import (
    HELLO_FLAG_SYNC_LOCKED,
    PREDICT_MIN_INTERVAL_SECONDS,
    SAMPLE_PERIOD_US,
    SoftTDMAHub,
    pack_data,
    pack_hello,
)


def stream_samples(hub, node_id, samples, start_time_us=0):
    hub.handle_packet(pack_hello(node_id, boot_id=node_id, flags=HELLO_FLAG_SYNC_LOCKED))
    for start in range(0, len(samples), 16):
        batch = samples[start:start + 16]
        hub.handle_packet(
            pack_data(node_id, start, start_time_us + (start * SAMPLE_PERIOD_US), batch)
        )


def test_build_prediction_windows_resamples_all_nodes():
    hub = SoftTDMAHub([1, 2])
    stream_samples(hub, 1, make_samples(76, offset=0.0))
    stream_samples(hub, 2, make_samples(76, offset=1.0))

    windows = hub.build_prediction_windows()

    assert windows is not None
    assert len(windows[1]) == 32
    assert len(windows[2]) == 32
    assert windows[1][0]["ax"] == pytest.approx(0.0, abs=0.15)
    assert windows[1][-1]["ax"] == pytest.approx(7.5, abs=0.2)
    assert windows[2][0]["ax"] == pytest.approx(1.0, abs=0.15)


def test_build_prediction_windows_requires_streaming_nodes_and_enough_history():
    not_streaming = SoftTDMAHub([1, 2])
    stream_samples(not_streaming, 1, make_samples(76))
    assert not_streaming.build_prediction_windows() is None

    too_short = SoftTDMAHub([1])
    stream_samples(too_short, 1, make_samples(2))
    assert too_short.build_prediction_windows() is None


def test_maybe_predict_updates_prediction_state_and_throttles():
    hub = SoftTDMAHub([1, 2])
    stream_samples(hub, 1, make_samples(76, offset=0.0))
    stream_samples(hub, 2, make_samples(76, offset=0.5))

    calls = []

    def fake_predict(active_nodes, windows):
        calls.append((active_nodes, windows))
        return True, {
            "activity": "walking",
            "confidence": 0.87,
            "used_node_ids": [2],
        }

    ok = hub.maybe_predict(fake_predict, now_monotonic=10.0)
    throttled = hub.maybe_predict(fake_predict, now_monotonic=10.0 + PREDICT_MIN_INTERVAL_SECONDS - 0.01)

    assert ok is True
    assert throttled is False
    assert len(calls) == 1
    assert calls[0][0] == [1, 2]
    assert hub.prediction_state["label"] == "walking"
    assert hub.prediction_state["confidence"] == 0.87
    assert hub.prediction_state["used_nodes"] == [2]
    assert hub.last_predict_monotonic == 10.0


def test_maybe_predict_marks_error_when_predictor_returns_unsuccessful_result():
    hub = SoftTDMAHub([1])
    stream_samples(hub, 1, make_samples(76))

    ok = hub.maybe_predict(lambda active_nodes, windows: (False, {"message": "boom"}), now_monotonic=20.0)

    assert ok is False
    assert hub.prediction_state["label"] == "ERROR"
    assert hub.prediction_state["confidence"] == "-"
    assert hub.prediction_state["used_nodes"] == [1]


def test_latest_table_rows_reports_latest_sample_per_node():
    hub = SoftTDMAHub([1, 2])
    stream_samples(hub, 1, make_samples(4, offset=0.0), start_time_us=100_000)
    stream_samples(hub, 2, make_samples(4, offset=1.0), start_time_us=200_000)

    rows = hub.latest_table_rows()

    assert rows[1]["t"] == int((100_000 + (3 * SAMPLE_PERIOD_US)) / 1000)
    assert rows[1]["ax"] == pytest.approx(0.3, abs=0.02)
    assert rows[2]["t"] == int((200_000 + (3 * SAMPLE_PERIOD_US)) / 1000)
    assert rows[2]["gz"] == pytest.approx(1.7, abs=0.02)
