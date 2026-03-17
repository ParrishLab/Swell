from __future__ import annotations

from unittest.mock import patch

from sdapp.shared.menu.factory import build_shared_menu


class _FakeRoot:
    def __init__(self):
        self.menu = None

    def config(self, **kwargs):
        self.menu = kwargs.get("menu")


class _FakeMenu:
    def __init__(self, *_args, **_kwargs):
        self.commands = []
        self.cascades = []

    def add_command(self, label, command=None, state="normal"):
        self.commands.append({"label": label, "state": state, "command": command})

    def add_separator(self):
        self.commands.append({"label": None, "state": "separator"})

    def add_cascade(self, label, menu):
        self.cascades.append({"label": label, "menu": menu})


class _App:
    def new_project(self):
        return None

    def open_project(self):
        return None

    def save_project(self):
        return None

    def save_project_as(self):
        return None

    def convert_to_project(self):
        return None

    def import_external_masks(self):
        return None

    def recover_autosave(self):
        return None

    def on_browse_model(self):
        return None

    def load_model_from_menu(self):
        return None

    def validate_assets_from_menu(self):
        return None

    def open_checkpoint_manager(self):
        return None

    def on_close(self):
        return None


def _file_menu(menu):
    return next(c["menu"] for c in menu.cascades if c["label"] == "File")


def _model_menu(menu):
    return next(c["menu"] for c in menu.cascades if c["label"] == "Model")


def _state_by_label(file_menu):
    return {item["label"]: item["state"] for item in file_menu.commands if item.get("label")}


def test_analysis_menu_omits_standalone_project_lifecycle_actions():
    root = _FakeRoot()
    app = _App()
    with patch("sdapp.shared.menu.factory.tk.Menu", _FakeMenu):
        menu = build_shared_menu(root, app, mode="analysis", host_mode=True)
    states = _state_by_label(_file_menu(menu))
    assert states["Save SD Project"] == "normal"
    assert "New Project" not in states
    assert "Open SD Project..." not in states
    assert "Convert to Project..." not in states
    assert "Recover Autosave..." not in states


def test_host_menu_keeps_project_lifecycle_actions_enabled():
    root = _FakeRoot()
    app = _App()
    with patch("sdapp.shared.menu.factory.tk.Menu", _FakeMenu):
        menu = build_shared_menu(root, app, mode="host", host_mode=False)
    states = _state_by_label(_file_menu(menu))
    assert states["New Project"] == "normal"
    assert states["Open SD Project..."] == "normal"
    assert states["Save SD Project"] == "normal"
    assert "Import Folder..." not in states
    assert "Set Output Folder..." not in states


def test_host_menu_exposes_checkpoint_manager_action():
    root = _FakeRoot()
    app = _App()
    with patch("sdapp.shared.menu.factory.tk.Menu", _FakeMenu):
        menu = build_shared_menu(root, app, mode="host", host_mode=False)
    model_states = _state_by_label(_model_menu(menu))
    assert model_states["Manage Checkpoints..."] == "normal"
