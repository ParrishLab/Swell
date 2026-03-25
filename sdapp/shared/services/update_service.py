from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import sys
from typing import TYPE_CHECKING, Callable
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET

from sdapp.shared.app_metadata import detect_app_version

if TYPE_CHECKING:
    from sdapp.analysis.core.state import AppConfig


SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
APPCAST_NAMESPACES = {"sparkle": SPARKLE_NS}
SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    download_url: str
    notes_url: str | None
    published_at: str | None
    title: str | None
    channel: str
    platform: str


@dataclass(frozen=True)
class UpdateCheckResult:
    status: str
    current_version: str
    latest: ReleaseInfo | None = None
    message: str | None = None


class _FrameworkUpdater:
    def is_available(self) -> bool:
        return False

    def install_release(self, release: ReleaseInfo) -> bool:
        return False


class _WinSparkleUpdater(_FrameworkUpdater):
    def __init__(self, dll_candidates: list[Path], appcast_url: str, current_version: str):
        self._dll_candidates = dll_candidates
        self._appcast_url = appcast_url
        self._current_version = current_version
        self._dll = None
        self._load()

    def _load(self) -> None:
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
        except Exception:
            return
        for candidate in self._dll_candidates:
            if not candidate.exists():
                continue
            try:
                dll = ctypes.WinDLL(str(candidate))
                dll.win_sparkle_set_appcast_url.argtypes = [ctypes.c_wchar_p]
                dll.win_sparkle_set_app_details.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
                dll.win_sparkle_set_app_build_version.argtypes = [ctypes.c_wchar_p]
                dll.win_sparkle_check_update_with_ui.argtypes = []
                dll.win_sparkle_init.argtypes = []
                dll.win_sparkle_set_appcast_url(self._appcast_url)
                dll.win_sparkle_set_app_details("Clay Dunford", "SDApp", self._current_version)
                dll.win_sparkle_set_app_build_version(self._current_version)
                dll.win_sparkle_init()
                self._dll = dll
                return
            except Exception:
                self._dll = None

    def is_available(self) -> bool:
        return self._dll is not None

    def install_release(self, release: ReleaseInfo) -> bool:  # noqa: ARG002
        if self._dll is None:
            return False
        try:
            self._dll.win_sparkle_check_update_with_ui()
            return True
        except Exception:
            return False


class _SparkleUpdater(_FrameworkUpdater):
    def __init__(self, bundle_candidates: list[Path]):
        self._bundle_candidates = bundle_candidates

    def is_available(self) -> bool:
        if sys.platform != "darwin":
            return False
        return any(candidate.exists() for candidate in self._bundle_candidates)

    def install_release(self, release: ReleaseInfo) -> bool:
        if not self.is_available():
            return False
        try:
            # A native bridge can replace this opener later without changing controller policy.
            return bool(webbrowser.open(release.download_url))
        except Exception:
            return False


class UpdateService:
    def __init__(
        self,
        *,
        version_provider: Callable[[], str] | None = None,
        urlopen: Callable[..., object] | None = None,
    ) -> None:
        self._version_provider = version_provider or self._detect_version
        self._urlopen = urlopen or urllib.request.urlopen

    def platform_key(self) -> str | None:
        if sys.platform.startswith("win"):
            return "windows"
        if sys.platform == "darwin":
            return "macos"
        return None

    def current_version(self) -> str:
        raw = str(self._version_provider() or "").strip()
        parsed = self._parse_version(raw)
        if parsed is None:
            return "0.0.0"
        return ".".join(str(part) for part in parsed)

    def should_check_automatically(self, config: "AppConfig", *, now: datetime | None = None) -> bool:
        if not config.auto_check_enabled:
            return False
        platform_name = self.platform_key()
        if platform_name is None:
            return False
        if not config.appcast_url_for_platform(platform_name):
            return False
        if not config.last_update_check_at:
            return True
        try:
            last_check = datetime.fromisoformat(config.last_update_check_at)
        except Exception:
            return True
        if last_check.tzinfo is None:
            last_check = last_check.replace(tzinfo=timezone.utc)
        check_now = now or datetime.now(timezone.utc)
        return check_now.astimezone(timezone.utc) - last_check.astimezone(timezone.utc) >= timedelta(days=1)

    def check_for_updates(
        self,
        config: "AppConfig",
        *,
        automatic: bool,
        now: datetime | None = None,
    ) -> UpdateCheckResult:
        current_version = self.current_version()
        platform_name = self.platform_key()
        if platform_name is None:
            return UpdateCheckResult(status="unsupported", current_version=current_version, message="Unsupported platform.")
        if automatic and not self.should_check_automatically(config, now=now):
            return UpdateCheckResult(status="deferred", current_version=current_version)

        appcast_url = config.appcast_url_for_platform(platform_name)
        if not appcast_url:
            return UpdateCheckResult(status="disabled", current_version=current_version, message="No update feed configured.")

        check_time = now or datetime.now(timezone.utc)
        config.mark_update_check(check_time)
        try:
            latest = self._fetch_latest_release(
                appcast_url=appcast_url,
                channel=config.release_channel,
                platform_name=platform_name,
            )
        except Exception as exc:
            return UpdateCheckResult(status="error", current_version=current_version, message=str(exc))

        if self._compare_versions(latest.version, current_version) <= 0:
            if config.ignored_version and self._compare_versions(config.ignored_version, current_version) <= 0:
                config.ignored_version = None
            return UpdateCheckResult(status="current", current_version=current_version, latest=latest)

        if automatic and config.ignored_version and self._compare_versions(latest.version, config.ignored_version) == 0:
            return UpdateCheckResult(status="ignored", current_version=current_version, latest=latest)
        return UpdateCheckResult(status="available", current_version=current_version, latest=latest)

    def ignore_release(self, config: "AppConfig", version: str) -> None:
        config.ignored_version = str(version).strip() or None

    def open_release(self, config: "AppConfig", release: ReleaseInfo) -> bool:
        appcast_url = config.appcast_url_for_platform(release.platform)
        if not appcast_url:
            return False
        framework = self._build_framework(platform_name=release.platform, appcast_url=appcast_url)
        if framework.install_release(release):
            return True
        try:
            return bool(webbrowser.open(release.download_url))
        except Exception:
            return False

    def _build_framework(self, *, platform_name: str, appcast_url: str) -> _FrameworkUpdater:
        runtime_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
        if platform_name == "windows":
            dll_candidates = [
                runtime_root / "WinSparkle.dll",
                runtime_root / "updater" / "windows" / "WinSparkle.dll",
                runtime_root / "sdapp" / "resources" / "updater" / "windows" / "WinSparkle.dll",
                runtime_root / "_internal" / "sdapp" / "resources" / "updater" / "windows" / "WinSparkle.dll",
            ]
            return _WinSparkleUpdater(dll_candidates, appcast_url, self.current_version())
        bundle_resources = runtime_root.parent / "Resources"
        bundle_frameworks = runtime_root.parent / "Frameworks"
        bundle_candidates = [
            bundle_frameworks / "Sparkle.framework",
            runtime_root / "Sparkle.framework",
            runtime_root / "updater" / "macos" / "Sparkle.framework",
            runtime_root / "sdapp" / "resources" / "updater" / "macos" / "Sparkle.framework",
            bundle_resources / "updater" / "macos" / "Sparkle.framework",
            bundle_resources / "sdapp" / "resources" / "updater" / "macos" / "Sparkle.framework",
        ]
        return _SparkleUpdater(bundle_candidates)

    def _fetch_latest_release(self, *, appcast_url: str, channel: str, platform_name: str) -> ReleaseInfo:
        with self._urlopen(appcast_url, timeout=10) as response:
            payload = response.read()
        root = ET.fromstring(payload)
        channel_node = root.find("channel")
        if channel_node is None:
            raise RuntimeError("Invalid appcast feed: missing channel node.")
        item = channel_node.find("item")
        if item is None:
            raise RuntimeError("Invalid appcast feed: missing item node.")

        enclosure = item.find("enclosure")
        if enclosure is None:
            raise RuntimeError("Invalid appcast feed: missing enclosure.")
        download_url = str(enclosure.attrib.get("url", "")).strip()
        if not download_url:
            raise RuntimeError("Invalid appcast feed: enclosure url missing.")

        version = (
            str(enclosure.attrib.get(f"{{{SPARKLE_NS}}}shortVersionString", "")).strip()
            or str(enclosure.attrib.get(f"{{{SPARKLE_NS}}}version", "")).strip()
        )
        if self._parse_version(version) is None:
            raise RuntimeError(f"Unsupported release version in appcast: {version!r}")

        notes_node = item.find("sparkle:releaseNotesLink", APPCAST_NAMESPACES)
        pub_date_node = item.find("pubDate")
        title_node = item.find("title")
        return ReleaseInfo(
            version=version.lstrip("v"),
            download_url=download_url,
            notes_url=notes_node.text.strip() if notes_node is not None and notes_node.text else None,
            published_at=pub_date_node.text.strip() if pub_date_node is not None and pub_date_node.text else None,
            title=title_node.text.strip() if title_node is not None and title_node.text else None,
            channel=channel,
            platform=platform_name,
        )

    def _detect_version(self) -> str:
        return detect_app_version()

    @staticmethod
    def _parse_version(raw: str) -> tuple[int, int, int] | None:
        match = SEMVER_RE.match(str(raw or "").strip())
        if not match:
            return None
        return tuple(int(part) for part in match.groups())

    def _compare_versions(self, left: str, right: str) -> int:
        parsed_left = self._parse_version(left)
        parsed_right = self._parse_version(right)
        if parsed_left is None or parsed_right is None:
            raise RuntimeError(f"Unable to compare versions: {left!r} vs {right!r}")
        if parsed_left < parsed_right:
            return -1
        if parsed_left > parsed_right:
            return 1
        return 0
