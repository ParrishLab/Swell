from __future__ import annotations

import importlib
import sys


def _clear_modules(*names: str) -> None:
    for name in names:
        sys.modules.pop(name, None)


def test_canonical_entrypoint_import() -> None:
    _clear_modules("sdapp.main", "sdapp.host.ui.root_window", "sdapp.host.app")
    import sdapp.main as sdapp_main

    assert callable(sdapp_main.main)
    assert "sdapp.host.ui.root_window" not in sys.modules
    assert "sdapp.host.app" not in sys.modules


def test_root_window_import_does_not_eagerly_load_host_app() -> None:
    _clear_modules("sdapp.host.ui.root_window", "sdapp.host.app")

    root_window = importlib.import_module("sdapp.host.ui.root_window")

    assert callable(root_window.run_host_app)
    assert "sdapp.host.app" not in sys.modules


def test_shared_services_package_import_is_lazy() -> None:
    _clear_modules(
        "sdapp.shared.services",
        "sdapp.shared.services.update_service",
        "sdapp.shared.services.unified_project_service",
        "sdapp.shared.services.instance_bridge",
    )

    services = importlib.import_module("sdapp.shared.services")

    assert "sdapp.shared.services.update_service" not in sys.modules
    assert "sdapp.shared.services.unified_project_service" not in sys.modules
    assert "sdapp.shared.services.instance_bridge" not in sys.modules

    bridge_cls = services.SingleInstanceBridge

    assert bridge_cls.__name__ == "SingleInstanceBridge"
    assert "sdapp.shared.services.instance_bridge" in sys.modules
    assert "sdapp.shared.services.update_service" not in sys.modules


def test_analysis_app_import_does_not_eagerly_load_model_runtime_modules() -> None:
    _clear_modules(
        "sdapp.analysis.app",
        "sdapp.analysis.core.segmentation",
        "sdapp.analysis.model",
        "sdapp.analysis.model.sam2_frame_cache",
        "sdapp.analysis.model.sam2_runtime",
        "torch",
        "sam2",
    )

    analysis_app = importlib.import_module("sdapp.analysis.app")

    assert callable(analysis_app.SDSegmentationApp)
    assert "torch" not in sys.modules
    assert "sam2" not in sys.modules
    assert "sdapp.analysis.model.sam2_frame_cache" not in sys.modules
    assert "sdapp.analysis.model.sam2_runtime" not in sys.modules


def test_dc_trace_controller_import_does_not_eagerly_load_matplotlib() -> None:
    _clear_modules(
        "sdapp.host.controllers.dc_trace_controller",
        "matplotlib",
        "matplotlib.backends.backend_tkagg",
        "matplotlib.figure",
    )

    controller_module = importlib.import_module("sdapp.host.controllers.dc_trace_controller")

    assert callable(controller_module.HostDCTraceController)
    assert "matplotlib.backends.backend_tkagg" not in sys.modules
    assert "matplotlib.figure" not in sys.modules
