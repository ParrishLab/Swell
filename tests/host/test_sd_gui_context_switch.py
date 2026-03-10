from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sdapp.host.sd_gui import SDAnalyzerApp


class _Mgr:
    def __init__(self, refs):
        self._refs = list(refs)
        self.closed = False

    def list_windows(self):
        return list(self._refs)

    def close_all(self):
        self.closed = True


def _app_with_refs(refs):
    app = SDAnalyzerApp.__new__(SDAnalyzerApp)
    app.analysis_window_manager = _Mgr(refs)
    app._analysis_windows = []
    app._show_warning = lambda *_args, **_kwargs: None
    return app


def test_close_analysis_windows_cancel_aborts():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch("sdapp.host.sd_gui.messagebox.askyesnocancel", return_value=None):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is False
    assert app.analysis_window_manager.closed is False


def test_close_analysis_windows_no_save_closes_all():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch("sdapp.host.sd_gui.messagebox.askyesnocancel", return_value=False):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is True
    assert app.analysis_window_manager.closed is True


def test_close_analysis_windows_save_then_continue_closes_all():
    def _save():
        dirty.project_dirty = False

    dirty = SimpleNamespace(project_dirty=True, save_project=_save)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch("sdapp.host.sd_gui.messagebox.askyesnocancel", return_value=True):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is True
    assert app.analysis_window_manager.closed is True


def test_close_analysis_windows_save_cancelled_aborts():
    dirty = SimpleNamespace(project_dirty=True, save_project=lambda: None)
    ref = SimpleNamespace(app=dirty)
    app = _app_with_refs([ref])
    with patch("sdapp.host.sd_gui.messagebox.askyesnocancel", return_value=True):
        result = app.close_analysis_windows_with_prompt()
    assert result["ok"] is False
    assert result["reason"] == "save_cancelled"
    assert app.analysis_window_manager.closed is False
