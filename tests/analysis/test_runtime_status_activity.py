from __future__ import annotations

from sdapp.analysis.app import SDSegmentationApp


class _DummyBar:
    def __init__(self) -> None:
        self.started = False
        self.mapped = False

    def winfo_ismapped(self) -> bool:
        return bool(self.mapped)

    def pack(self, **_kwargs) -> None:
        self.mapped = True

    def pack_forget(self) -> None:
        self.mapped = False

    def start(self, _speed: int) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


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
    assert bar.started is True
    assert config_updates == []

    app._set_runtime_status("Propagation Complete", "green")
    assert var.value == "Propagation Complete"
    assert bar.started is False
    assert config_updates == []
