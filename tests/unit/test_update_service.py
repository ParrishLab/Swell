from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from swell.shared.config import AppConfig
from swell.shared.services.update_service import UpdateService


APPCAST = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>Swell windows stable releases</title>
    <item>
      <title>Swell 0.1.4</title>
      <pubDate>Mon, 23 Mar 2026 12:00:00 +0000</pubDate>
      <sparkle:releaseNotesLink>https://github.com/ClayDunford/Swell/releases/tag/v0.1.4</sparkle:releaseNotesLink>
      <enclosure
        url="https://github.com/ClayDunford/Swell/releases/download/v0.1.4/Swell-Setup-0.1.4.exe"
        length="123"
        type="application/octet-stream"
        sparkle:version="0.1.4"
        sparkle:shortVersionString="0.1.4" />
    </item>
  </channel>
</rss>
"""


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        self.close()
        return False


def _service(platform_key: str = "windows") -> UpdateService:
    service = UpdateService(version_provider=lambda: "0.1.3", urlopen=lambda *_args, **_kwargs: _Response(APPCAST))
    service.platform_key = lambda: platform_key
    return service


def _config() -> AppConfig:
    return AppConfig(
        default_output="output",
        default_model="managed://sam2.1_hiera_base_plus",
        default_baseline=30,
        auto_check_enabled=True,
        release_channel="stable",
        update_channels={"stable": {"windows": "https://example.test/swell-windows.xml"}},
    )


def test_should_check_automatically_requires_daily_interval() -> None:
    cfg = _config()
    cfg.last_update_check_at = "2026-03-23T10:00:00+00:00"
    service = _service()

    assert service.should_check_automatically(cfg, now=datetime(2026, 3, 23, 18, 0, tzinfo=timezone.utc)) is False
    assert service.should_check_automatically(cfg, now=datetime(2026, 3, 24, 10, 1, tzinfo=timezone.utc)) is True


def test_check_for_updates_returns_available_release() -> None:
    cfg = _config()
    service = _service()

    result = service.check_for_updates(cfg, automatic=False, now=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc))

    assert result.status == "available"
    assert result.latest is not None
    assert result.latest.version == "0.1.4"
    assert cfg.last_update_check_at == "2026-03-23T12:00:00+00:00"


def test_automatic_check_honors_ignored_version() -> None:
    cfg = _config()
    cfg.ignored_version = "0.1.4"
    cfg.last_update_check_at = None
    service = _service()

    result = service.check_for_updates(cfg, automatic=True, now=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc))

    assert result.status == "ignored"


def test_manual_check_bypasses_ignored_version() -> None:
    cfg = _config()
    cfg.ignored_version = "0.1.4"
    service = _service()

    result = service.check_for_updates(cfg, automatic=False, now=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc))

    assert result.status == "available"
