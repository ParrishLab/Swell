from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Sequence


def run_git(
    repo_root: str | Path,
    args: Sequence[str],
    *,
    check: bool = False,
    stderr: int | None = subprocess.PIPE,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run Git without forking the long-lived, multithreaded app process."""
    git_executable = shutil.which("git")
    if git_executable is None:
        raise FileNotFoundError("git executable not found")

    # A full executable path, no cwd override, and close_fds=False make this
    # eligible for CPython's os.posix_spawn path on macOS. Forking after Torch,
    # Tk, and SAM2 have started threads can trigger libmalloc warnings and is
    # unsafe in general; `git -C` lets us avoid the cwd option that forces fork.
    command = [git_executable, "-C", str(Path(repo_root)), *map(str, args)]
    return subprocess.run(
        command,
        check=check,
        stdout=subprocess.PIPE,
        stderr=stderr,
        text=True,
        timeout=timeout,
        close_fds=False,
    )
