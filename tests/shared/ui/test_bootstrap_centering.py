from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from swell.shared.ui.bootstrap import center_window_on_screen


class _FakeWindow:
    def __init__(self) -> None:
        self.geometry_value = None

    def update_idletasks(self) -> None:
        return

    def winfo_width(self) -> int:
        return 0

    def winfo_height(self) -> int:
        return 1

    def winfo_reqwidth(self) -> int:
        return 480

    def winfo_reqheight(self) -> int:
        return 220

    def winfo_screenwidth(self) -> int:
        return 1920

    def winfo_screenheight(self) -> int:
        return 1080

    def geometry(self, value: str) -> None:
        self.geometry_value = value


def test_center_window_on_screen_uses_requested_size_when_needed():
    window = _FakeWindow()

    center_window_on_screen(window)

    assert window.geometry_value == "480x220+720+430"


def test_center_window_on_screen_preserves_explicit_size_override():
    window = _FakeWindow()

    center_window_on_screen(window, width=1400, height=950)

    assert window.geometry_value == "1400x950+260+65"


class _FakeWindowWithGeometryString(_FakeWindow):
    def __init__(self, initial_geometry: str) -> None:
        super().__init__()
        self.geometry_value = initial_geometry

    def geometry(self, value: str = None) -> str | None:
        if value is None:
            return self.geometry_value
        self.geometry_value = value
        return None


def test_center_window_on_screen_clears_placeholder_geometry():
    window = _FakeWindowWithGeometryString("680x1+0+0")
    window.winfo_width = lambda: 680
    window.winfo_height = lambda: 1
    window.winfo_reqwidth = lambda: 680
    window.winfo_reqheight = lambda: 350

    center_window_on_screen(window, width=680)

    # With width=680, height=None, and initial height=1, center_window_on_screen should
    # clear the geometry, update idletasks, and fall back to winfo_reqheight (350).
    # Screen width = 1920, screen height = 1080.
    # x = (1920 - 680) // 2 = 620
    # y = (1080 - 350) // 2 = 365
    assert window.geometry_value == "680x350+620+365"



class _FakeWindowWithMinsize(_FakeWindow):
    def __init__(self, min_w: int, min_h: int, *, screen: tuple[int, int] = (1366, 768)) -> None:
        super().__init__()
        self.min_size = (int(min_w), int(min_h))
        self.screen = screen

    def winfo_screenwidth(self) -> int:
        return self.screen[0]

    def winfo_screenheight(self) -> int:
        return self.screen[1]

    def minsize(self, width: int | None = None, height: int | None = None):
        if width is None and height is None:
            return self.min_size
        self.min_size = (int(width), int(height))
        return None


def test_center_window_on_screen_clamps_request_to_screen():
    # 850 tall does not fit a 768px display once OS chrome is accounted for.
    window = _FakeWindowWithMinsize(0, 0)

    center_window_on_screen(window, width=1200, height=850)

    assert window.geometry_value == "1200x688+83+40"


def test_center_window_on_screen_relaxes_minsize_larger_than_screen():
    window = _FakeWindowWithMinsize(1200, 850)

    center_window_on_screen(window, width=1200, height=850)

    assert window.min_size == (1200, 688)
    assert window.geometry_value == "1200x688+83+40"


def test_center_window_on_screen_leaves_fitting_minsize_alone():
    window = _FakeWindowWithMinsize(1000, 620, screen=(1920, 1080))

    center_window_on_screen(window, width=1200, height=850)

    assert window.min_size == (1000, 620)
    assert window.geometry_value == "1200x850+360+115"
