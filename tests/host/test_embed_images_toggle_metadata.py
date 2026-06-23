from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from swell.host.app import SwellHostApp, format_bytes


def _fake_app(value: bool):
    metadata_calls: list[dict] = []
    var_values: list[bool] = []
    session = SimpleNamespace(set_metadata=lambda **kw: metadata_calls.append(kw))
    var = SimpleNamespace(get=lambda: value, set=lambda v: var_values.append(bool(v)))
    app = SimpleNamespace(
        embed_images_menu_var=var,
        browser_controller=SimpleNamespace(session=session),
        stack_info=SimpleNamespace(input_dir="/tmp/frames"),
        input_var=SimpleNamespace(get=lambda: ""),
        root=object(),
        _set_status=lambda _text: None,
    )
    # Bind the real confirm method to the fake; stub only the filesystem size estimate.
    app._embedded_images_size_estimate = lambda: (3, 1024)
    app._confirm_embed_source_images = lambda: SwellHostApp._confirm_embed_source_images(app)
    return app, metadata_calls, var_values


def test_toggle_on_confirmed_persists_embed_flag():
    app, metadata_calls, var_values = _fake_app(True)
    with patch("swell.host.app.messagebox.askyesno", return_value=True):
        SwellHostApp.toggle_embed_source_images(app)
    assert metadata_calls == [{"embed_source_images": True}]
    assert var_values == []  # not reverted


def test_toggle_on_cancelled_reverts_and_skips_metadata():
    app, metadata_calls, var_values = _fake_app(True)
    with patch("swell.host.app.messagebox.askyesno", return_value=False):
        SwellHostApp.toggle_embed_source_images(app)
    assert metadata_calls == []
    assert var_values == [False]  # checkbox reverted


def test_toggle_off_persists_without_prompt():
    app, metadata_calls, var_values = _fake_app(False)
    with patch("swell.host.app.messagebox.askyesno") as askyesno:
        SwellHostApp.toggle_embed_source_images(app)
    assert askyesno.called is False
    assert metadata_calls == [{"embed_source_images": False}]


def test_format_bytes_units():
    assert format_bytes(512) == "512 B"
    assert format_bytes(2048) == "2.0 KB"
    assert format_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert format_bytes(3 * 1024 * 1024 * 1024) == "3.0 GB"
