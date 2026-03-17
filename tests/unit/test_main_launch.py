from __future__ import annotations

import importlib
import sys
import types
from typing import Sequence


def _load_main_module(monkeypatch):
    fake_root_window = types.ModuleType("sdapp.host.ui.root_window")
    fake_root_window.run_host_app = lambda **_kwargs: None
    monkeypatch.setitem(sys.modules, "sdapp.host.ui.root_window", fake_root_window)
    sys.modules.pop("sdapp.main", None)
    return importlib.import_module("sdapp.main")


def test_parse_launch_project_path_uses_first_positional(monkeypatch) -> None:
    main_mod = _load_main_module(monkeypatch)
    args = ["sdapp", "--flag", "", "demo.sdproj", "ignored.sdproj"]
    assert main_mod._parse_launch_project_path(args) == "demo.sdproj"


def test_parse_main_args_detects_smoke_flag(monkeypatch) -> None:
    main_mod = _load_main_module(monkeypatch)
    smoke, smoke_model_runtime, project_path = main_mod._parse_main_args(
        ["sdapp", "--smoke-test", "/tmp/example.sdproj"]
    )
    assert smoke is True
    assert smoke_model_runtime is False
    assert project_path == "/tmp/example.sdproj"


def test_parse_main_args_detects_model_runtime_smoke_flag(monkeypatch) -> None:
    main_mod = _load_main_module(monkeypatch)
    smoke, smoke_model_runtime, project_path = main_mod._parse_main_args(
        ["sdapp", "--smoke-test", "--smoke-model-runtime", "/tmp/example.sdproj"]
    )
    assert smoke is True
    assert smoke_model_runtime is True
    assert project_path == "/tmp/example.sdproj"


def test_main_forwards_open_request_to_running_instance(monkeypatch) -> None:
    main_mod = _load_main_module(monkeypatch)

    class _Bridge:
        def __init__(self) -> None:
            self.sent: list[str] = []

        def send_open_request(self, path: str) -> bool:
            self.sent.append(path)
            return True

    created: list[_Bridge] = []
    run_calls: list[tuple[Sequence[str], object]] = []
    freeze_calls: list[str] = []

    def _bridge_factory():
        bridge = _Bridge()
        created.append(bridge)
        return bridge

    monkeypatch.setattr(main_mod, "SingleInstanceBridge", _bridge_factory)
    monkeypatch.setattr(main_mod.multiprocessing, "freeze_support", lambda: freeze_calls.append("freeze"))
    monkeypatch.setattr(
        main_mod,
        "run_host_app",
        lambda **kwargs: run_calls.append((kwargs.get("initial_project_path"), kwargs.get("instance_bridge"))),
    )

    rc = main_mod.main(["sdapp", "/tmp/example.sdproj"])

    assert rc == 0
    assert freeze_calls == ["freeze"]
    assert len(created) == 1
    assert created[0].sent == ["/tmp/example.sdproj"]
    assert run_calls == []


def test_main_runs_host_app_when_no_running_instance(monkeypatch) -> None:
    main_mod = _load_main_module(monkeypatch)

    class _Bridge:
        def send_open_request(self, _path: str) -> bool:
            return False

    run_calls: list[tuple[str | None, object]] = []
    freeze_calls: list[str] = []

    monkeypatch.setattr(main_mod, "SingleInstanceBridge", lambda: _Bridge())
    monkeypatch.setattr(main_mod.multiprocessing, "freeze_support", lambda: freeze_calls.append("freeze"))
    monkeypatch.setattr(
        main_mod,
        "run_host_app",
        lambda **kwargs: run_calls.append((kwargs.get("initial_project_path"), kwargs.get("instance_bridge"))),
    )

    rc = main_mod.main(["sdapp", "/tmp/example.sdproj"])

    assert rc == 0
    assert freeze_calls == ["freeze"]
    assert len(run_calls) == 1
    assert run_calls[0][0] == "/tmp/example.sdproj"
    assert run_calls[0][1] is not None


def test_main_smoke_test_pass(monkeypatch, capsys) -> None:
    main_mod = _load_main_module(monkeypatch)
    freeze_calls: list[str] = []
    monkeypatch.setattr(main_mod.multiprocessing, "freeze_support", lambda: freeze_calls.append("freeze"))
    monkeypatch.setattr(main_mod, "_run_smoke_test", lambda **_kwargs: (True, "ok"))

    rc = main_mod.main(["sdapp", "--smoke-test"])
    out = capsys.readouterr().out.strip()

    assert rc == 0
    assert freeze_calls == ["freeze"]
    assert out == "SMOKE_TEST:PASS"


def test_main_smoke_test_fail(monkeypatch, capsys) -> None:
    main_mod = _load_main_module(monkeypatch)
    monkeypatch.setattr(main_mod, "_run_smoke_test", lambda **_kwargs: (False, "broken:ImportError:nope"))

    rc = main_mod.main(["sdapp", "--smoke-test"])
    out = capsys.readouterr().out.strip()

    assert rc == 1
    assert out == "SMOKE_TEST:FAIL:broken:ImportError:nope"


def test_main_smoke_test_skips_instance_bridge_even_with_project_path(monkeypatch, capsys) -> None:
    main_mod = _load_main_module(monkeypatch)
    bridge_calls: list[str] = []
    run_calls: list[str] = []

    class _Bridge:
        def send_open_request(self, path: str) -> bool:
            bridge_calls.append(path)
            return True

    monkeypatch.setattr(main_mod, "SingleInstanceBridge", lambda: _Bridge())
    monkeypatch.setattr(main_mod, "run_host_app", lambda **_kwargs: run_calls.append("run"))
    monkeypatch.setattr(main_mod, "_run_smoke_test", lambda **_kwargs: (True, "ok"))

    rc = main_mod.main(["sdapp", "--smoke-test", "/tmp/example.sdproj"])
    out = capsys.readouterr().out.strip()

    assert rc == 0
    assert out == "SMOKE_TEST:PASS"
    assert bridge_calls == []
    assert run_calls == []


def test_run_smoke_test_success_with_injected_importer(monkeypatch) -> None:
    main_mod = _load_main_module(monkeypatch)

    loaded: list[str] = []

    def _importer(name: str):
        loaded.append(name)
        return object()

    ok, detail = main_mod._run_smoke_test(importer=_importer)
    assert ok is True
    assert detail == "ok"
    assert "sdapp.host.ui.root_window" in loaded


def test_run_smoke_test_returns_failure_details(monkeypatch) -> None:
    main_mod = _load_main_module(monkeypatch)
    target = "sdapp.shared.persistence.unified_project_store"

    def _importer(name: str):
        if name == target:
            raise ImportError("missing")
        return object()

    ok, detail = main_mod._run_smoke_test(importer=_importer)
    assert ok is False
    assert detail.startswith(f"{target}:ImportError:missing")


def test_run_smoke_test_model_runtime_imports_requested(monkeypatch) -> None:
    main_mod = _load_main_module(monkeypatch)

    loaded: list[str] = []

    def _importer(name: str):
        loaded.append(name)
        return object()

    ok, detail = main_mod._run_smoke_test(importer=_importer, include_model_runtime=True)
    assert ok is True
    assert detail == "ok"
    assert "torch" in loaded
    assert "sam2" in loaded
