from __future__ import annotations


def test_canonical_entrypoint_import() -> None:
    import sdapp.main as sdapp_main

    assert callable(sdapp_main.main)
