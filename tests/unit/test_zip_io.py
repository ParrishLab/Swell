from __future__ import annotations

import os
import time

from swell.shared.persistence import zip_io


def test_cleanup_stale_extract_dirs_counts_only_removed_directories(tmp_path, monkeypatch) -> None:
    stale = tmp_path / f"{zip_io.EMBEDDED_EXTRACT_PREFIX}stale"
    stale.mkdir()
    old = time.time() - 3600
    os.utime(stale, (old, old))
    monkeypatch.setattr(zip_io.shutil, "rmtree", lambda *_args, **_kwargs: None)

    removed = zip_io.cleanup_stale_extract_dirs(older_than_sec=60, root=tmp_path)

    assert removed == 0
    assert stale.exists()


def test_cleanup_stale_extract_dirs_counts_successful_removal(tmp_path) -> None:
    stale = tmp_path / f"{zip_io.EMBEDDED_EXTRACT_PREFIX}stale"
    stale.mkdir()
    old = time.time() - 3600
    os.utime(stale, (old, old))

    removed = zip_io.cleanup_stale_extract_dirs(older_than_sec=60, root=tmp_path)

    assert removed == 1
    assert not stale.exists()
