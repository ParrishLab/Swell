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

    app._set_runtime_status("Propagating...", "orange")
    assert var.value == "Propagating..."
    assert bar.started is False
    assert bar.mapped is False
    assert config_updates == []

    app._set_runtime_status("Propagation Complete", "green")
    assert var.value == "Propagation Complete"
    assert bar.started is False
    assert config_updates == []


def test_propagation_progress_uses_determinate_bar() -> None:
    app = SDSegmentationApp.__new__(SDSegmentationApp)
    bar = _DummyBar()
    var = _DummyVar()

    app.loading_bar = bar
    app.loading_status_var = var
    app._loading_task_count = 0
    app._propagation_progress_active = False

    app._apply_propagation_progress_update(active=True, done=3, total=10, label="Propagation", status="progress", run_id=2)
    assert bar.mode == "determinate"
    assert bar.value == 3
    assert bar.maximum == 10
    assert bar.mapped is True
    assert var.value == "Propagation 30% (3/10)"

    app._apply_propagation_progress_update(active=False, done=10, total=10, label="Propagation", status="complete", run_id=2)
    assert bar.mapped is False
    assert bar.value == 0
    assert var.value == "Propagation complete"
