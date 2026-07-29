"""Browser regression coverage for the interactive documentation demos.

Run locally with:

    python -m pip install -e ".[docs-test]"
    python -m playwright install chromium chromium-headless-shell
    python -m pytest -q tests/docs
"""

from __future__ import annotations

import functools
import http.server
import os
from pathlib import Path
import socketserver
import subprocess
import sys
import threading
from collections.abc import Iterator

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
PlaywrightError = playwright_sync_api.Error
sync_playwright = playwright_sync_api.sync_playwright


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEMO_PAGES = (
    ("/user-guide/3-mark-events/", "[data-swell-event-range-demo] .swell-event-range-demo__shell", 1),
    ("/user-guide/4-open-analysis/", "[data-swell-open-analysis-demo] .swell-open-analysis-demo__shell", 1),
    ("/user-guide/5-segment-events/", "main canvas", 3),
    ("/user-guide/6-propagate-masks/", "[data-swell-propagation-demo] .swell-propagation-demo__canvas", 1),
    ("/user-guide/7-review-overlays/", "[data-swell-propagation-demo] .swell-propagation-demo__canvas", 2),
)
VIEWPORTS = (
    pytest.param({"width": 1440, "height": 1000}, id="desktop"),
    pytest.param({"width": 375, "height": 812}, id="mobile"),
)


@pytest.fixture(scope="session")
def built_docs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    site_dir = tmp_path_factory.mktemp("site")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "--site-dir",
            os.fspath(site_dir),
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    return site_dir


@pytest.fixture(scope="session")
def docs_url(built_docs: Path) -> Iterator[str]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=os.fspath(built_docs))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        server.allow_reuse_address = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        if not executable.exists():
            pytest.skip("Chromium is not installed; run `python -m playwright install chromium chromium-headless-shell`.")
        try:
            browser = playwright.chromium.launch()
        except PlaywrightError as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip("Chromium headless shell is not installed; run `python -m playwright install chromium chromium-headless-shell`.")
            raise
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(browser, docs_url: str):
    context = browser.new_context()
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"page error: {error}"))
    page.on(
        "console",
        lambda message: errors.append(f"console error: {message.text}")
        if message.type == "error" and not message.text.startswith("Failed to load resource:")
        else None,
    )
    page.on(
        "response",
        lambda response: errors.append(f"local response error: {response.status} {response.url}")
        if response.status >= 400 and response.url.startswith(docs_url)
        else None,
    )
    try:
        yield page, errors
    finally:
        context.close()


def goto_demo(page, docs_url: str, path: str, mounted_selector: str, expected_mounts: int) -> None:
    page.goto(f"{docs_url}{path}", wait_until="networkidle")
    page.locator(mounted_selector).nth(expected_mounts - 1).wait_for(state="visible")


def assert_page_fits_viewport(page) -> None:
    overflow = page.evaluate("""() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
    })""")
    assert overflow["scrollWidth"] <= overflow["clientWidth"], overflow


@pytest.mark.parametrize(("path", "mounted_selector", "expected_mounts"), DEMO_PAGES)
@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_demo_pages_mount_without_errors_or_horizontal_overflow(
    page,
    docs_url: str,
    path: str,
    mounted_selector: str,
    expected_mounts: int,
    viewport: dict[str, int],
) -> None:
    browser_page, errors = page
    browser_page.set_viewport_size(viewport)

    goto_demo(browser_page, docs_url, path, mounted_selector, expected_mounts)

    assert_page_fits_viewport(browser_page)
    assert not errors


def test_demo_controls_respond_to_basic_interactions(page, docs_url: str) -> None:
    browser_page, errors = page
    browser_page.set_viewport_size({"width": 1440, "height": 1000})

    goto_demo(browser_page, docs_url, "/user-guide/3-mark-events/", "[data-swell-event-range-demo] .swell-event-range-demo__shell", 1)
    event_range = browser_page.locator("[data-swell-event-range-demo]")
    event_range.get_by_role("slider", name="Preview frame").fill("42")
    event_range.get_by_role("button", name="Set Start").click()
    event_range.get_by_role("button", name="Confirm").click()
    assert "simulation confirmed" in event_range.locator(".swell-event-range-demo__sr-status").inner_text().lower()

    goto_demo(browser_page, docs_url, "/user-guide/4-open-analysis/", "[data-swell-open-analysis-demo] .swell-open-analysis-demo__shell", 1)
    open_analysis = browser_page.locator("[data-swell-open-analysis-demo]")
    assert open_analysis.get_by_role("spinbutton", name="Baseline Frames").input_value() == "30"
    assert "30 requested; 12 available." in open_analysis.inner_text()
    for label, checked in (("Horizontal Bar Denoise", False), ("Smoothing", True), ("Baseline Subtraction", True), ("Global Normalization", True), ("Stabilize", False)):
        assert open_analysis.get_by_role("checkbox", name=label).is_checked() is checked
    open_analysis.get_by_role("checkbox", name="Smoothing").uncheck()
    assert "settings changed" in open_analysis.inner_text().lower()
    open_analysis.get_by_role("button", name="Show Preview").click()
    open_analysis.get_by_role("checkbox", name="Stabilize").check()
    assert "settings changed" in open_analysis.inner_text().lower()
    assert open_analysis.get_by_role("button", name="Show Preview").is_enabled()
    open_analysis.get_by_role("button", name="Show Preview").click()
    open_analysis.get_by_text("Preview updated.").wait_for()

    goto_demo(browser_page, docs_url, "/user-guide/5-segment-events/", "main canvas", 3)
    prompt = browser_page.locator("[data-swell-prompt-demo]")
    prompt.get_by_role("button", name="Add Point (+)").click()
    prompt.locator("canvas").click(position={"x": 180, "y": 120})
    assert "simulated" in prompt.locator(".swell-prompt-demo__sr-status").inner_text().lower()

    mask_edit = browser_page.locator("[data-swell-mask-edit-demo]")
    mask_edit.get_by_role("slider", name="Brush size").fill("18")
    assert mask_edit.locator("output").inner_text() == "18 px"
    mask_edit.locator("canvas").drag_to(mask_edit.locator("canvas"), source_position={"x": 110, "y": 130}, target_position={"x": 180, "y": 130})
    assert "mask painted" in mask_edit.locator(".swell-mask-edit-demo__sr-status").inner_text().lower()

    regions = browser_page.locator("[data-swell-region-demo]")
    regions.get_by_role("button", name="Include Region").click()
    canvas = regions.locator("canvas")
    for position in ({"x": 150, "y": 120}, {"x": 210, "y": 125}, {"x": 180, "y": 175}):
        canvas.click(position=position)
    regions.get_by_role("button", name="Close Shape").click()
    regions.get_by_role("button", name="Add Region").click()
    assert "include region added" in regions.locator(".swell-region-demo__sr-status").inner_text().lower()

    goto_demo(browser_page, docs_url, "/user-guide/6-propagate-masks/", "[data-swell-propagation-demo] .swell-propagation-demo__canvas", 1)
    propagation = browser_page.locator("[data-swell-propagation-demo]")
    propagation.get_by_role("button", name="Run Propagation").click()
    browser_page.wait_for_function(
        """() => {
            const button = document.querySelector("[data-swell-propagation-demo] button");
            return button && !button.disabled;
        }"""
    )
    assert "drifted" in propagation.locator(".swell-propagation-demo__sr-status").inner_text().lower()

    goto_demo(browser_page, docs_url, "/user-guide/7-review-overlays/", "[data-swell-propagation-demo] .swell-propagation-demo__canvas", 2)
    ghosts = browser_page.locator("[data-swell-propagation-demo='ghosts']")
    ghosts.get_by_role("checkbox", name="Ghost Outlines").check()
    assert ghosts.get_by_role("checkbox", name="Ghost Outlines").is_checked()
    leverage = browser_page.locator("[data-swell-propagation-demo='leverage']")
    leverage.get_by_role("button", name="Jump to Suggested Correction").click()
    assert leverage.get_by_role("slider", name="Current frame").input_value() != "1"

    assert_page_fits_viewport(browser_page)
    assert not errors


def test_instant_navigation_remounts_demos(page, docs_url: str) -> None:
    browser_page, errors = page
    browser_page.set_viewport_size({"width": 1440, "height": 1000})

    goto_demo(
        browser_page,
        docs_url,
        "/user-guide/3-mark-events/",
        "[data-swell-event-range-demo] .swell-event-range-demo__shell",
        1,
    )
    browser_page.locator("a[href$='4-open-analysis/']").first.click()
    browser_page.locator("[data-swell-open-analysis-demo] .swell-open-analysis-demo__shell").wait_for(state="visible")
    assert browser_page.locator("[data-swell-open-analysis-demo] .swell-open-analysis-demo__shell").count() == 1

    browser_page.locator("a[href$='3-mark-events/']").first.click()
    browser_page.locator("[data-swell-event-range-demo] .swell-event-range-demo__shell").wait_for(state="visible")
    assert browser_page.locator("[data-swell-event-range-demo] .swell-event-range-demo__shell").count() == 1

    goto_demo(browser_page, docs_url, "/user-guide/5-segment-events/", "main canvas", 3)
    browser_page.locator("a[href$='6-propagate-masks/']").first.click()
    browser_page.locator("[data-swell-propagation-demo] .swell-propagation-demo__canvas").wait_for(state="visible")
    assert browser_page.locator("[data-swell-propagation-demo] .swell-propagation-demo__canvas").count() == 1

    browser_page.locator("a[href$='5-segment-events/']").first.click()
    browser_page.locator("[data-swell-prompt-demo] canvas").wait_for(state="visible")
    assert browser_page.locator("main canvas").count() == 3
    assert_page_fits_viewport(browser_page)
    assert not errors
