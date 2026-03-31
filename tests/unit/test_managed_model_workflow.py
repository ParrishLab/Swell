from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sdapp.shared.ui.managed_model_workflow import (
    ManagedModelWorkflow,
    ManagedModelWorkflowOptions,
)


class _FakeDialog:
    def __init__(self, root):
        self.root = root
        self.destroyed = False

    def title(self, _value: str) -> None:
        return None

    def transient(self, _root) -> None:
        return None

    def resizable(self, *_args) -> None:
        return None

    def grab_set(self) -> None:
        return None

    def destroy(self) -> None:
        self.destroyed = True

    def update_idletasks(self) -> None:
        return None

    def minsize(self, *_args) -> None:
        return None

    def winfo_width(self) -> int:
        return 400

    def winfo_height(self) -> int:
        return 200


class _FakeWidget:
    def __init__(self, *_args, **_kwargs) -> None:
        return None

    def pack(self, **_kwargs) -> None:
        return None

    def configure(self, **_kwargs) -> None:
        return None


class _FakeLabel(_FakeWidget):
    pass


class _FakeFrame(_FakeWidget):
    pass


class _FakeVar:
    def __init__(self, value: str = "") -> None:
        self.value = str(value)

    def set(self, value: str) -> None:
        self.value = str(value)

    def get(self) -> str:
        return self.value


class _FakeTreeview(_FakeWidget):
    def __init__(self, *_args, **_kwargs) -> None:
        self.rows: dict[str, tuple[str, str]] = {}
        self._selection: list[str] = []

    def heading(self, *_args, **_kwargs) -> None:
        return None

    def column(self, *_args, **_kwargs) -> None:
        return None

    def insert(self, _parent: str, _index: str, iid: str, values: tuple[str, str]) -> None:
        self.rows[str(iid)] = tuple(values)

    def get_children(self):
        return list(self.rows.keys())

    def delete(self, item: str) -> None:
        self.rows.pop(str(item), None)

    def selection_set(self, item: str) -> None:
        self._selection = [str(item)]

    def selection(self):
        return list(self._selection)

    def focus(self, _item: str) -> None:
        return None


class _FakeButton(_FakeWidget):
    def __init__(self, root, *_args, text: str = "", command=None, **_kwargs) -> None:
        self.text = str(text)
        self.command = command
        root._buttons[self.text] = self

    def configure(self, *, command=None, state=None) -> None:
        if command is not None:
            self.command = command
        self.state = state

    def invoke(self) -> None:
        if callable(self.command):
            self.command()


class _FakeRoot:
    def __init__(self, action_label: str) -> None:
        self.action_label = action_label
        self._buttons: dict[str, _FakeButton] = {}

    def wait_window(self, _dialog) -> None:
        self._buttons[self.action_label].invoke()


class _ImmediateRunner:
    def start(self, target, *, on_success=None, on_error=None, **_kwargs):
        try:
            result = target()
        except Exception as exc:  # noqa: BLE001
            if callable(on_error):
                on_error(exc)
            return object()
        if callable(on_success):
            on_success(result)
        return object()


@dataclass(frozen=True)
class _Descriptor:
    checkpoint_id: str
    filename: str


class _Service:
    def __init__(self) -> None:
        self.descriptor = _Descriptor("sam2", "sam2.pt")
        self.downloaded = False

    def load_catalog(self):
        return [self.descriptor]

    def managed_models_dir(self) -> str:
        return "/tmp/models"

    def descriptor_path(self, descriptor: _Descriptor):
        class _Path:
            def __init__(self, exists: bool) -> None:
                self._exists = exists

            def exists(self) -> bool:
                return self._exists

        return _Path(self.downloaded)

    def download_descriptor(self, descriptor: _Descriptor) -> str:
        assert descriptor == self.descriptor
        self.downloaded = True
        return "/tmp/models/sam2.pt"


def _patch_ui(monkeypatch, root: _FakeRoot) -> None:
    import sdapp.shared.ui.managed_model_workflow as workflow_module

    monkeypatch.setattr(workflow_module.tk, "Toplevel", lambda _root: _FakeDialog(root))
    monkeypatch.setattr(workflow_module.tk, "StringVar", _FakeVar)
    monkeypatch.setattr(workflow_module.ttk, "Frame", _FakeFrame)
    monkeypatch.setattr(workflow_module.ttk, "Label", _FakeLabel)
    monkeypatch.setattr(workflow_module.ttk, "Treeview", _FakeTreeview)
    monkeypatch.setattr(workflow_module.ttk, "Button", lambda *args, **kwargs: _FakeButton(root, *args, **kwargs))


def test_managed_model_workflow_uses_selected_descriptor(monkeypatch) -> None:
    root = _FakeRoot("Use Selected")
    _patch_ui(monkeypatch, root)
    service = _Service()
    service.downloaded = True
    calls: list[tuple[str, str]] = []
    workflow = ManagedModelWorkflow(
        root=root,
        service=service,
        runner=_ImmediateRunner(),
        options=ManagedModelWorkflowOptions(
            title="Models",
            select_local_title="Select Model",
            unavailable_message="unavailable",
            empty_catalog_message="empty",
        ),
        get_current_managed_id=lambda: None,
        on_log_info=lambda _msg: None,
        on_log_error=lambda _msg: None,
        activate_managed=lambda descriptor, source: calls.append((descriptor.checkpoint_id, source)) or True,
        activate_local=lambda _path, _source: True,
        prompt_select_local=lambda _parent, _title: None,
    )

    result = workflow.open_dialog(required=False)

    assert result["ok"] is True
    assert calls == [("sam2", "managed_select")]


def test_managed_model_workflow_downloads_before_activation(monkeypatch) -> None:
    root = _FakeRoot("Download Selected")
    _patch_ui(monkeypatch, root)
    service = _Service()
    calls: list[tuple[str, str]] = []
    workflow = ManagedModelWorkflow(
        root=root,
        service=service,
        runner=_ImmediateRunner(),
        options=ManagedModelWorkflowOptions(
            title="Models",
            select_local_title="Select Model",
            unavailable_message="unavailable",
            empty_catalog_message="empty",
        ),
        get_current_managed_id=lambda: None,
        on_log_info=lambda _msg: None,
        on_log_error=lambda _msg: None,
        activate_managed=lambda descriptor, source: calls.append((descriptor.checkpoint_id, source)) or True,
        activate_local=lambda _path, _source: True,
        prompt_select_local=lambda _parent, _title: None,
    )

    result = workflow.open_dialog(required=False)

    assert result["ok"] is True
    assert service.downloaded is True
    assert calls == [("sam2", "managed_download")]


def test_managed_model_workflow_selects_local_path(monkeypatch) -> None:
    root = _FakeRoot("Select Local...")
    _patch_ui(monkeypatch, root)
    service = _Service()
    calls: list[tuple[str, str]] = []
    workflow = ManagedModelWorkflow(
        root=root,
        service=service,
        runner=_ImmediateRunner(),
        options=ManagedModelWorkflowOptions(
            title="Models",
            select_local_title="Select Model",
            unavailable_message="unavailable",
            empty_catalog_message="empty",
        ),
        get_current_managed_id=lambda: None,
        on_log_info=lambda _msg: None,
        on_log_error=lambda _msg: None,
        activate_managed=lambda _descriptor, _source: True,
        activate_local=lambda path, source: calls.append((path, source)) or True,
        prompt_select_local=lambda _parent, _title: "/tmp/local.pt",
    )

    result = workflow.open_dialog(required=False)

    assert result["ok"] is True
    assert calls == [(str(Path("/tmp/local.pt").resolve()), "manual_override")]
