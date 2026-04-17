from __future__ import annotations

import threading
from tkinter import messagebox

from sdapp.shared.config import AppConfig
from sdapp.shared.services.update_service import UpdateCheckResult, UpdateService
from sdapp.shared.ui import BackgroundTaskRunner


class HostUpdateController:
    def __init__(self, app, service: UpdateService | None = None):
        self.app = app
        self.service = service or UpdateService()
        self._active_check: threading.Thread | None = None

    def schedule_startup_check(self) -> None:
        config = self._config()
        if not self.service.should_check_automatically(config):
            return
        self.app.root.after(1200, lambda: self._start_check(automatic=True))

    def check_for_updates(self) -> None:
        self._start_check(automatic=False)

    def _start_check(self, *, automatic: bool) -> None:
        thread = self._task_runner().start(
            lambda: self._run_check(automatic=automatic),
            key="host_update_check",
            drop_if_running=True,
        )
        if thread is not None:
            self._active_check = thread

    def _run_check(self, *, automatic: bool) -> None:
        config = self._config()
        result = self.service.check_for_updates(config, automatic=automatic)
        self._persist_config(config)
        self.app.root.after(0, lambda r=result, a=automatic: self._handle_result(r, automatic=a))

    def _handle_result(self, result: UpdateCheckResult, *, automatic: bool) -> None:
        if result.status in {"deferred", "ignored"}:
            return
        if result.status == "available" and result.latest is not None:
            self._prompt_for_release(result)
            return
        if automatic:
            if result.status == "error":
                self.app._log_warn(f"Automatic update check failed: {result.message}")
            return
        if result.status == "current":
            messagebox.showinfo("Check for Updates", "You are already running the latest stable release.", parent=self.app.root)
            return
        if result.status == "unsupported":
            messagebox.showinfo("Check for Updates", "Automatic updates are not supported on this platform.", parent=self.app.root)
            return
        if result.status == "disabled":
            messagebox.showwarning("Check for Updates", "No stable update feed is configured.", parent=self.app.root)
            return
        if result.status == "error":
            messagebox.showerror("Check for Updates", f"Unable to check for updates.\n\n{result.message}", parent=self.app.root)

    def _prompt_for_release(self, result: UpdateCheckResult) -> None:
        release = result.latest
        if release is None:
            return
        response = messagebox.askyesnocancel(
            "Update Available",
            (
                f"SDApp {release.version} is available.\n"
                f"You are running {result.current_version}.\n\n"
                "Yes: download and install now.\n"
                "No: not now.\n"
                "Cancel: ignore this version."
            ),
            parent=self.app.root,
        )
        if response is None:
            config = self._config()
            self.service.ignore_release(config, release.version)
            self._persist_config(config)
            return
        if response is False:
            return
        config = self._config()
        opened = self.service.open_release(config, release)
        self._persist_config(config)
        if opened:
            return
        messagebox.showerror(
            "Update Available",
            "The updater could not start the install flow for this release.",
            parent=self.app.root,
        )

    def _config(self) -> AppConfig:
        config = getattr(self.app, "config", None)
        if isinstance(config, AppConfig):
            return config
        config = AppConfig.load()
        self.app.config = config
        return config

    def _persist_config(self, config: AppConfig) -> None:
        self.app.config = config
        config.save()

    def _task_runner(self) -> BackgroundTaskRunner:
        runner = getattr(self.app, "_background_task_runner", None)
        if isinstance(runner, BackgroundTaskRunner):
            return runner
        runner = BackgroundTaskRunner(self.app.root)
        self.app._background_task_runner = runner
        return runner
