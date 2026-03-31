from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sdapp.host.dc_trace import WaveSurferH5Adapter


class _FakeDataset:
    def __init__(self, value, *, forbid_full_read: bool = False) -> None:
        self._value = np.asarray(value)
        self.shape = self._value.shape
        self.dtype = self._value.dtype
        self._forbid_full_read = bool(forbid_full_read)

    def __getitem__(self, key):
        if key == ():
            if self._forbid_full_read:
                raise AssertionError("full dataset read was not expected")
            return self._value
        return self._value[key]


class _FakeGroup(dict):
    def __getitem__(self, key):
        if isinstance(key, str) and "/" in key:
            node = self
            for part in [segment for segment in key.split("/") if segment]:
                node = dict.__getitem__(node, part)
            return node
        return dict.__getitem__(self, key)

    def keys(self):
        return dict.keys(self)


class _FakeFile(_FakeGroup):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


def _fake_h5_module(tree: _FakeFile):
    return SimpleNamespace(File=lambda _path, _mode: tree)


def _valid_tree() -> _FakeFile:
    return _FakeFile(
        {
            "header": _FakeGroup(
                {
                    "AcquisitionSampleRate": _FakeDataset(200.0),
                    "Acquisition": _FakeGroup(
                        {
                            "AnalogScalingCoefficients": _FakeDataset([0.0, 2.0, 0.0, 0.0]),
                            "AnalogChannelNames": _FakeDataset([b"LFP 1", b"Ignored", b"LFP 2"]),
                            "AnalogChannelUnits": _FakeDataset([b"mV", b"mV", b"mV"]),
                            "AnalogChannelScales": _FakeDataset([0.5, 1.0, 0.5]),
                            "IsAnalogChannelActive": _FakeDataset([True, False, True]),
                        }
                    ),
                }
            ),
            "sweep_0001": _FakeGroup({"analogScans": _FakeDataset(np.asarray([[1, 2], [3, 4], [5, 6]], dtype=np.int16))}),
            "sweep_0002": _FakeGroup({"analogScans": _FakeDataset(np.asarray([[7, 8], [9, 10]], dtype=np.int16))}),
        }
    )


def _metadata_only_tree() -> _FakeFile:
    return _FakeFile(
        {
            "header": _FakeGroup(
                {
                    "AcquisitionSampleRate": _FakeDataset(50.0),
                    "Acquisition": _FakeGroup(
                        {
                            "AnalogChannelNames": _FakeDataset([b"LFP 1"]),
                            "AnalogChannelUnits": _FakeDataset([b"mV"]),
                            "AnalogChannelScales": _FakeDataset([1.0]),
                        }
                    ),
                }
            ),
            "sweep_0001": _FakeGroup(
                {"analogScans": _FakeDataset(np.zeros((1000, 1), dtype=np.int16), forbid_full_read=True)}
            ),
            "sweep_0002": _FakeGroup(
                {"analogScans": _FakeDataset(np.zeros((2000, 1), dtype=np.int16), forbid_full_read=True)}
            ),
        }
    )


def _legacy_channel_first_tree() -> _FakeFile:
    return _FakeFile(
        {
            "header": _FakeGroup(
                {
                    "AcquisitionSampleRate": _FakeDataset([[10000.0]]),
                    "AIChannelNames": _FakeDataset([b"LFP", b"Pico"]),
                    "AIChannelUnits": _FakeDataset([b"mV", b"V"]),
                    "AIChannelScales": _FakeDataset([[0.01], [1.0]]),
                    "IsAIChannelActive": _FakeDataset([[1.0], [1.0]]),
                    "AIScalingCoefficients": _FakeDataset(
                        [
                            [-0.5, 0.25, 0.0, 0.0],
                            [1.0, 1.0, 0.0, 0.0],
                        ]
                    ),
                }
            ),
            "sweep_0001": _FakeGroup(
                {
                    "analogScans": _FakeDataset(
                        np.asarray(
                            [
                                [2, 6, 10, 14],
                                [1, 2, 3, 4],
                            ],
                            dtype=np.int16,
                        )
                    )
                }
            ),
        }
    )


def test_wavesurfer_metadata_reads_active_channels(monkeypatch) -> None:
    adapter = WaveSurferH5Adapter()
    monkeypatch.setattr("sdapp.host.dc_trace._load_h5py", lambda: _fake_h5_module(_valid_tree()))

    metadata = adapter.load_metadata(Path("/tmp/example.h5"))

    assert metadata["source_type"] == "wavesurfer_h5"
    assert metadata["channel_names"] == ["LFP 1", "LFP 2"]
    assert metadata["units"] == ["mV", "mV"]
    assert float(metadata["sample_rate_hz"]) == 200.0
    assert metadata["segments"] == [[0, 3], [3, 5]]
    assert int(metadata["sweep_count"]) == 2


def test_wavesurfer_load_trace_scales_and_concatenates_sweeps(monkeypatch) -> None:
    adapter = WaveSurferH5Adapter()
    monkeypatch.setattr("sdapp.host.dc_trace._load_h5py", lambda: _fake_h5_module(_valid_tree()))

    record = adapter.load_trace(Path("/tmp/example.h5"), channel_selection=1)

    assert record.channel_names == ["LFP 2"]
    assert record.units == ["mV"]
    assert record.segments == [(0, 3), (3, 5)]
    assert record.signals.shape == (5, 1)
    assert np.array_equal(np.asarray(record.signals[:, 0]), np.asarray([4.0, 8.0, 12.0, 16.0, 20.0]))


def test_wavesurfer_load_trace_returns_expected_scaled_values(monkeypatch) -> None:
    adapter = WaveSurferH5Adapter()
    monkeypatch.setattr("sdapp.host.dc_trace._load_h5py", lambda: _fake_h5_module(_valid_tree()))

    record = adapter.load_trace(Path("/tmp/example.h5"), channel_selection=0)

    assert np.array_equal(np.asarray(record.signals[:, 0]), np.asarray([4.0, 12.0, 20.0, 28.0, 36.0]))


def test_wavesurfer_metadata_rejects_missing_sweeps(monkeypatch) -> None:
    adapter = WaveSurferH5Adapter()
    tree = _FakeFile({"header": _FakeGroup({})})
    monkeypatch.setattr("sdapp.host.dc_trace._load_h5py", lambda: _fake_h5_module(tree))

    with pytest.raises(ValueError):
        adapter.load_metadata(Path("/tmp/invalid.h5"))


def test_wavesurfer_metadata_does_not_read_full_analog_datasets(monkeypatch) -> None:
    adapter = WaveSurferH5Adapter()
    monkeypatch.setattr("sdapp.host.dc_trace._load_h5py", lambda: _fake_h5_module(_metadata_only_tree()))

    metadata = adapter.load_metadata(Path("/tmp/large.h5"))

    assert metadata["segments"] == [[0, 1000], [1000, 3000]]
    assert int(metadata["total_samples"]) == 3000


def test_wavesurfer_legacy_header_and_channel_first_layout(monkeypatch) -> None:
    adapter = WaveSurferH5Adapter()
    monkeypatch.setattr("sdapp.host.dc_trace._load_h5py", lambda: _fake_h5_module(_legacy_channel_first_tree()))

    metadata = adapter.load_metadata(Path("/tmp/legacy.h5"))
    record = adapter.load_trace(Path("/tmp/legacy.h5"), channel_selection=0)

    assert metadata["channel_names"] == ["LFP", "Pico"]
    assert metadata["units"] == ["mV", "V"]
    assert metadata["segments"] == [[0, 4]]
    assert int(metadata["total_samples"]) == 4
    assert float(metadata["duration_s"]) == 4 / 10000.0
    assert np.array_equal(np.asarray(record.signals[:, 0]), np.asarray([0.0, 100.0, 200.0, 300.0]))
