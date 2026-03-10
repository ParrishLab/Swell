from __future__ import annotations


def test_entrypoint_modules_import() -> None:
    import sdapp.host.main as host_main
    import sdapp.main as sdapp_main

    assert callable(sdapp_main.main)
    assert callable(host_main.main)
