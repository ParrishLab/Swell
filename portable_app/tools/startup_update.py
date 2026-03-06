#!/usr/bin/env python3
import shutil
import subprocess
import sys
from pathlib import Path


EXPECTED_BRANCH = "release"
EXPECTED_HTTPS_REMOTE = "https://github.com/ParrishLab/IOS-Analysis-Code.git"
EXPECTED_SSH_REMOTE = "git@github.com:ParrishLab/IOS-Analysis-Code.git"


def log(message: str) -> None:
    print(f"[UPDATER] {message}")


def warn(message: str) -> None:
    print(f"[UPDATER] WARN: {message}")


def run_cmd(args, cwd: Path, timeout: int = 20):
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def update_startup() -> int:
    repo_root = Path.cwd()
    python_exec = sys.executable

    if shutil.which("git") is None:
        warn("git is not installed or not on PATH; skipping update.")
        return 0

    rc, out, err = run_cmd(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_root)
    if rc != 0 or out.lower() != "true":
        warn("current directory is not a git working tree; skipping update.")
        return 0

    rc, branch, err = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    if rc != 0:
        warn(f"unable to read current branch; skipping update. {err}")
        return 0
    if branch != EXPECTED_BRANCH:
        warn(f"branch is '{branch}', expected '{EXPECTED_BRANCH}'; skipping update.")
        return 0

    rc, remote_url, err = run_cmd(["git", "remote", "get-url", "origin"], cwd=repo_root)
    if rc != 0:
        warn(f"unable to read origin remote; skipping update. {err}")
        return 0

    if remote_url == EXPECTED_SSH_REMOTE:
        rc, out, err = run_cmd(
            ["git", "remote", "set-url", "origin", EXPECTED_HTTPS_REMOTE],
            cwd=repo_root,
        )
        if rc != 0:
            warn(f"failed to switch origin to HTTPS; skipping update. {err}")
            return 0
        log("switched origin remote to HTTPS.")
    elif remote_url == EXPECTED_HTTPS_REMOTE:
        pass
    else:
        warn(f"unexpected origin remote '{remote_url}'; continuing with existing remote.")

    rc, status_out, err = run_cmd(["git", "status", "--porcelain"], cwd=repo_root)
    if rc != 0:
        warn(f"unable to read git status; skipping update. {err}")
        return 0
    if status_out:
        warn("local changes detected; skipping update.")
        return 0

    rc, old_head, err = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root)
    if rc != 0:
        warn(f"unable to read current revision; skipping update. {err}")
        return 0

    rc, out, err = run_cmd(["git", "fetch", "--prune", "origin", EXPECTED_BRANCH], cwd=repo_root, timeout=60)
    if rc != 0:
        warn(f"fetch failed; skipping update. {err}")
        return 0

    rc, remote_head, err = run_cmd(["git", "rev-parse", f"origin/{EXPECTED_BRANCH}"], cwd=repo_root)
    if rc != 0:
        warn(f"unable to read remote revision; skipping update. {err}")
        return 0

    if old_head == remote_head:
        log("up-to-date.")
        return 0

    log("new release revision found; applying fast-forward update.")
    rc, out, err = run_cmd(
        ["git", "pull", "--ff-only", "origin", EXPECTED_BRANCH],
        cwd=repo_root,
        timeout=120,
    )
    if rc != 0:
        warn(f"fast-forward pull failed; skipping update. {err}")
        return 0

    rc, new_head, err = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root)
    if rc != 0:
        warn(f"unable to read updated revision; continuing without dependency sync. {err}")
        return 0

    rc, changed_files, err = run_cmd(["git", "diff", "--name-only", old_head, new_head], cwd=repo_root)
    if rc != 0:
        warn(f"unable to compute changed files; continuing without dependency sync. {err}")
        return 0

    changed = {line.strip() for line in changed_files.splitlines() if line.strip()}
    if "requirements.txt" in changed:
        log("requirements.txt changed; syncing dependencies.")
        rc, out, err = run_cmd(
            [python_exec, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=repo_root,
            timeout=1200,
        )
        if rc != 0:
            warn(f"dependency sync failed; continuing launch. {err}")
            return 0
        log("dependency sync complete.")
    else:
        log("requirements unchanged; skipping dependency sync.")

    log("update complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(update_startup())
    except Exception as exc:
        warn(f"unexpected updater error; continuing launch. {exc}")
        sys.exit(0)
