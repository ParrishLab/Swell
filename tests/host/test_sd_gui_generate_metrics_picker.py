from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from sdapp.host.sd_gui import SDAnalyzerApp


class _Var:
    def __init__(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value


def test_metrics_picker_initial_dir_prefers_input_folder(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.input_var = _Var(str(input_dir))
    app.stack_info = SimpleNamespace(input_dir=str(tmp_path / "other"))

    resolved = app._metrics_picker_initial_dir()
    assert resolved == str(input_dir.resolve())


def test_load_metrics_reference_image_prefers_stack_reader_mapping(tmp_path: Path) -> None:
    image_path = tmp_path / "frame_0001.tif"
    Image.fromarray(np.full((4, 4), 10, dtype=np.uint8)).save(image_path)
    reader_frame = np.array([[1, 2], [3, 4]], dtype=np.uint16)

    class _Reader:
        def get_frame_count(self):
            return 1

        def get_frame_ref(self, _idx):
            return SimpleNamespace(source_path=image_path)

        def read_frame(self, _idx, use_cache=True):  # noqa: ARG002
            return reader_frame

    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.reader = _Reader()

    loaded = app._load_metrics_reference_image_u8(str(image_path))

    assert loaded is not None
    assert loaded.dtype == np.uint8
    assert np.array_equal(loaded, app._preview_to_u8(reader_frame))


def test_pick_metrics_reference_image_validates_shape(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    selected = input_dir / "picked.tif"
    Image.fromarray(np.zeros((2, 2), dtype=np.uint8)).save(selected)

    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.input_var = _Var(str(input_dir))
    app.stack_info = SimpleNamespace(frame_height=8, frame_width=9)
    warnings: list[tuple[str, str]] = []
    app._show_warning = lambda title, msg: warnings.append((str(title), str(msg)))
    app._load_metrics_reference_image_u8 = lambda _path: np.zeros((2, 2), dtype=np.uint8)

    captured = {}

    def _pick(**kwargs):
        captured.update(kwargs)
        return str(selected)

    monkeypatch.setattr("sdapp.host.sd_gui.filedialog.askopenfilename", _pick)

    result = app._pick_metrics_reference_image_u8(parent=None, purpose="ROI")

    assert result is None
    assert captured.get("initialdir") == str(input_dir.resolve())
    assert "parent" not in captured
    assert warnings


def test_pick_metrics_reference_image_prefills_current_active_frame(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    selected = input_dir / "frame_0002.tif"
    Image.fromarray(np.zeros((8, 9), dtype=np.uint8)).save(selected)

    class _Reader:
        def get_frame_count(self):
            return 2

        def get_frame_ref(self, idx):
            name = "frame_0001.tif" if int(idx) == 0 else "frame_0002.tif"
            return SimpleNamespace(source_path=input_dir / name)

    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.reader = _Reader()
    app.current_frame_idx = 1
    app.input_var = _Var(str(input_dir))
    app.stack_info = SimpleNamespace(frame_height=8, frame_width=9)
    app._show_warning = lambda *_args, **_kwargs: None
    app._load_metrics_reference_image_u8 = lambda _path: np.zeros((8, 9), dtype=np.uint8)

    captured = {}

    def _pick(**kwargs):
        captured.update(kwargs)
        return str(selected)

    monkeypatch.setattr("sdapp.host.sd_gui.filedialog.askopenfilename", _pick)

    result = app._pick_metrics_reference_image_u8(parent=None, purpose="ROI")

    assert result is not None
    assert captured.get("initialdir") == str(input_dir.resolve())
    assert captured.get("initialfile") == "frame_0002.tif"
    assert "parent" not in captured


def test_pick_metrics_reference_image_reuses_last_scale_image_path(monkeypatch, tmp_path: Path) -> None:
    selected = tmp_path / "scale_ref.tif"
    Image.fromarray(np.zeros((8, 9), dtype=np.uint8)).save(selected)

    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app._last_scale_image_path = str(selected)
    app.stack_info = SimpleNamespace(frame_height=8, frame_width=9)
    app._show_warning = lambda *_args, **_kwargs: None
    app._load_metrics_reference_image_u8 = lambda path: np.zeros((8, 9), dtype=np.uint8) if str(path) == str(selected) else None

    def _unexpected_picker(**_kwargs):
        raise AssertionError("file picker should not be opened when last scale image exists")

    monkeypatch.setattr("sdapp.host.sd_gui.filedialog.askopenfilename", _unexpected_picker)

    result = app._pick_metrics_reference_image_u8(parent=None, purpose="Scale")

    assert result is not None
