from __future__ import annotations

from sdapp.analysis.app import SDSegmentationApp


class _DummyBar:
    def __init__(self) -> None:
        self.started = False
        self.mapped = False
        self.mode = "indeterminate"
        self.value = 0
        self.maximum = 100

    def winfo_ismapped(self) -> bool:
        return bool(self.mapped)

    def grid(self, **_kwargs) -> None:
        self.mapped = True

    def grid_remove(self) -> None:
        self.mapped = False

    def start(self, _speed: int) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def configure(self, **kwargs) -> None:
        if "mode" in kwargs:
            self.mode = str(kwargs["mode"])
        if "value" in kwargs:
            self.value = kwargs["value"]
        if "maximum" in kwargs:
            self.maximum = kwargs["maximum"]


class _DummyVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = str(value)


class _DummyRoot:
    def __init__(self) -> None:
        self.after_calls = []
        self.cancelled = []
        self._next_job = 1

    def after(self, delay, callback):
        job = f"job-{self._next_job}"
        self._next_job += 1
        self.after_calls.append((int(delay), callback, job))
        return job

    def after_cancel(self, job):
        self.cancelled.append(job)


class _DummyCanvas:
    def __init__(self) -> None:
        self.items = []
        self.deleted_tags = []
        self.raised_tags = []
        self._next_id = 1

    def delete(self, *_args) -> None:
        self.deleted_tags.extend(str(arg) for arg in _args)
        if "all" in _args:
            self.items.clear()
            return
        tags = {str(arg) for arg in _args}
        self.items = [item for item in self.items if tags.isdisjoint(set(item["tags"]))]

    def winfo_width(self) -> int:
        return 120

    def winfo_height(self) -> int:
        return 10

    def create_rectangle(self, *args, **kwargs) -> int:
        item_id = self._next_id
        self._next_id += 1
        tags = kwargs.get("tags", ())
        if isinstance(tags, str):
            tags = (tags,)
        self.items.append({"id": item_id, "coords": tuple(args), "kwargs": dict(kwargs), "tags": tuple(tags)})
        return item_id

    def coords(self, item_id, *args):
        for item in self.items:
            if item["id"] == item_id:
                if args:
                    item["coords"] = tuple(args)
                return item["coords"]
        return ()

    def type(self, item_id):
        return "rectangle" if any(item["id"] == item_id for item in self.items) else ""

    def tag_raise(self, tag):
        self.raised_tags.append(str(tag))


def _install_slider_overlay(app, *, frame_count: int = 10, width: int = 120) -> _DummyCanvas:
    canvas = _DummyCanvas()
    app.slider_overlay = canvas
    app.slider_jump_markers = {}
    app.propagated_frame_indices = set()
    app._slider_overlay_regions = []
    app._slider_marker_bounds = {}
    app._build_frame_spans = lambda _indices: []
    app.log_debug = lambda *_args, **_kwargs: None
    app._get_frame_count = lambda: frame_count
    app._frame_to_overlay_x = (
        lambda frame_idx, width=width, total_frames=frame_count: (float(frame_idx) + 0.5) * float(width) / float(total_frames)
    )
    return canvas


def _install_ui_root(app) -> _DummyRoot:
    root = _DummyRoot()
    app.root = root
    app._ui_alive = lambda: True
    app._timeline_loading_animation_job = None
    return root


def test_runtime_status_updates_activity_loader_not_config_label() -> None:
    app = SDSegmentationApp.__new__(SDSegmentationApp)
    bar = _DummyBar()
    var = _DummyVar()
    config_updates: list[tuple[str, str]] = []

    app.loading_bar = bar
    app.loading_status_var = var
    app._loading_task_count = 0
    app.lbl_status = type(
        "Label",
        (),
        {"configure": staticmethod(lambda **kwargs: config_updates.append((kwargs.get("text", ""), kwargs.get("foreground", ""))))},
    )()
    _install_slider_overlay(app)

    app._set_runtime_status("Propagating...", "orange")
    assert var.value == "Propagating..."
    assert bar.started is False
    assert bar.mapped is False
    assert config_updates == []

    app._set_runtime_status("Propagation Complete", "green")
    assert var.value == "Propagation Complete"
    assert bar.started is False
    assert config_updates == []


def test_model_loading_uses_slider_overlay_progress_layer() -> None:
    app = SDSegmentationApp.__new__(SDSegmentationApp)
    bar = _DummyBar()
    var = _DummyVar()

    app.loading_bar = bar
    app.loading_status_var = var
    app._loading_task_count = 0
    app._propagation_progress_active = False
    canvas = _install_slider_overlay(app, frame_count=10)
    root = _install_ui_root(app)

    app._set_loading_indicator(True, "Loading model")
    assert bar.mode == "indeterminate"
    assert bar.started is False
    assert bar.mapped is False
    assert var.value == "Loading model"
    assert app._timeline_progress_state["kind"] == "loading"
    assert canvas.items
    assert len(root.after_calls) == 1
    assert root.after_calls[0][0] == 33

    app._set_loading_indicator(True, "Still loading")
    assert len(root.after_calls) == 1

    scheduled_job = app._timeline_loading_animation_job
    app._set_loading_indicator(False)
    assert bar.started is False
    assert bar.mapped is False
    assert app._timeline_progress_state is None
    assert scheduled_job in root.cancelled
    assert "timeline_progress" in canvas.deleted_tags


def test_propagation_progress_uses_timeline_state_not_loading_bar() -> None:
    app = SDSegmentationApp.__new__(SDSegmentationApp)
    bar = _DummyBar()
    var = _DummyVar()

    app.loading_bar = bar
    app.loading_status_var = var
    app._loading_task_count = 0
    app._propagation_progress_active = False
    canvas = _install_slider_overlay(app, frame_count=20)

    app._apply_propagation_progress_update(
        active=True,
        done=3,
        total=10,
        label="Propagation",
        status="progress",
        run_id=2,
        prop_start=4,
        prop_end=12,
        anchor=7,
        direction="forward",
        phase_done=2,
        phase_total=5,
    )
    assert bar.mapped is False
    assert var.value == "Propagation 30% (3/10)"
    assert app._propagation_progress_active is True
    assert app._timeline_progress_state["prop_start"] == 4
    assert app._timeline_progress_state["prop_end"] == 12
    assert app._timeline_progress_state["anchor"] == 7
    assert canvas.items

    app._apply_propagation_progress_update(active=False, done=10, total=10, label="Propagation", status="complete", run_id=2)
    assert bar.mapped is False
    assert bar.value == 0
    assert app._propagation_progress_active is False
    assert app._timeline_progress_state is None
    assert var.value == "Propagation complete"
