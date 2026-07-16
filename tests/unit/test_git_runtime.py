from __future__ import annotations

import subprocess

import pytest

from swell.shared import git_runtime


def test_run_git_uses_posix_spawn_eligible_arguments(monkeypatch, tmp_path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(git_runtime.shutil, "which", lambda _name: "/usr/bin/git")

    def _run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "release\n", "")

    monkeypatch.setattr(git_runtime.subprocess, "run", _run)

    result = git_runtime.run_git(
        tmp_path,
        ["rev-parse", "--abbrev-ref", "HEAD"],
        timeout=2,
    )

    assert result.stdout == "release\n"
    assert calls == [
        (
            [
                "/usr/bin/git",
                "-C",
                str(tmp_path),
                "rev-parse",
                "--abbrev-ref",
                "HEAD",
            ],
            {
                "check": False,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "timeout": 2,
                "close_fds": False,
            },
        )
    ]


def test_run_git_fails_cleanly_when_git_is_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(git_runtime.shutil, "which", lambda _name: None)

    with pytest.raises(FileNotFoundError, match="git executable not found"):
        git_runtime.run_git(tmp_path, ["status"])
