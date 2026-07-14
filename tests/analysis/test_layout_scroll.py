from swell.analysis.ui.layout import LayoutBuilder
from swell.analysis.core.region_tools import REGION_INCLUDE_TOOL


class _FakeRoot:
    def __init__(self):
        self.class_bindings = {}

    def bind_class(self, tag, sequence, func=None, add=None):  # noqa: ARG002
        self.class_bindings[(tag, sequence)] = func

    def unbind_class(self, tag, sequence):
        self.class_bindings.pop((tag, sequence), None)


class _FakeWidget:
    def __init__(self, *, rootx=0, rooty=0, width=100, height=100, children=None):
        self._rootx = rootx
        self._rooty = rooty
        self._width = width
        self._height = height
        self._children = list(children or [])
        self._bindtags = ("Widget",)
        self.scrolls = []

    def bindtags(self, tags=None):
        if tags is None:
            return self._bindtags
        self._bindtags = tuple(tags)
        return self._bindtags

    def winfo_children(self):
        return list(self._children)

    def winfo_rootx(self):
        return self._rootx

    def winfo_rooty(self):
        return self._rooty

    def winfo_width(self):
        return self._width

    def winfo_height(self):
        return self._height

    def yview_scroll(self, units, what):
        self.scrolls.append((units, what))


class _Event:
    def __init__(self, *, x_root=10, y_root=10, delta=0, num=None):
        self.x_root = x_root
        self.y_root = y_root
        self.delta = delta
        self.num = num


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _FakeFrame:
    def __init__(self):
        self.grid_count = 0
        self.remove_count = 0

    def grid(self):
        self.grid_count += 1

    def grid_remove(self):
        self.remove_count += 1


class _FakeButton:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)


class _FakeLabel(_FakeButton):
    pass


class _FakeSegState:
    def get_persistent_region(self, _region_id):
        return None


class _FakeRegionController:
    def __init__(self):
        self.points = []
        self.closed = False

    def get_region_draft_points(self):
        return list(self.points)

    def is_region_draft_closed(self):
        return self.closed


class _App(LayoutBuilder):
    def __init__(self):
        self.root = _FakeRoot()
        self.inspector_child = _FakeWidget()
        self.inspector_scroll_body = _FakeWidget(children=[self.inspector_child])
        self.inspector_scroll_canvas = _FakeWidget(rootx=100, rooty=100, width=200, height=300)
        self._inspector_wheel_bound = False


def test_inspector_mousewheel_uses_scoped_bindtag() -> None:
    app = _App()

    app._bind_inspector_mouse_wheel()

    assert ("InspectorWheel", "<MouseWheel>") in app.root.class_bindings
    assert "InspectorWheel" in app.inspector_scroll_canvas.bindtags()
    assert "InspectorWheel" in app.inspector_scroll_body.bindtags()
    assert "InspectorWheel" in app.inspector_child.bindtags()


def test_region_options_refresh_when_active_panel_is_unchanged() -> None:
    app = LayoutBuilder()
    region_frame = _FakeFrame()
    app.tool_option_frames = {
        "select": _FakeFrame(),
        REGION_INCLUDE_TOOL: region_frame,
    }
    app._active_tool_option_frame = region_frame
    app.tool_mode = _Var(REGION_INCLUDE_TOOL)
    app.selected_region_id = None
    app.seg_state = _FakeSegState()
    app.interaction_controller = _FakeRegionController()
    app.lbl_region_options_title = _FakeLabel()
    app.btn_region_convert = _FakeButton()
    app.btn_region_add = _FakeButton()
    app.btn_region_close_shape = _FakeButton()
    app.btn_region_discard = _FakeButton()

    app._sync_tool_options()
    assert app.btn_region_add.options["state"] == "disabled"
    assert app.btn_region_close_shape.options["state"] == "disabled"
    assert app.btn_region_discard.options["state"] == "disabled"

    app.interaction_controller.points = [(1, 1), (2, 1), (2, 2)]
    app._sync_tool_options()

    assert app.btn_region_add.options["state"] == "disabled"
    assert app.btn_region_close_shape.options["state"] == "normal"
    assert app.btn_region_discard.options["state"] == "normal"

    app.interaction_controller.closed = True
    app._sync_tool_options()

    assert app.btn_region_add.options["state"] == "normal"
    assert app.btn_region_close_shape.options["state"] == "disabled"
    assert region_frame.grid_count == 0
    assert region_frame.remove_count == 0


def test_entering_region_tool_discards_draft_clears_selection_and_resets_range() -> None:
    app = LayoutBuilder()
    app.tool_mode = _Var(REGION_INCLUDE_TOOL)
    app._last_handled_tool_mode = "select"
    app.selected_region_id = "region_a"
    calls = []
    app.interaction_controller = type(
        "Controller",
        (),
        {"on_tool_mode_changed": lambda _self, previous, current: calls.append((previous, current))},
    )()
    app._set_selected_region_id = lambda value: setattr(app, "selected_region_id", value)
    app._reset_region_options_to_default_range = lambda: calls.append("reset_range")
    app._sync_tool_mode_buttons = lambda: None
    app._sync_tool_options = lambda: None
    app._queue_display_update = lambda _preview: None

    app._on_tool_mode_changed()

    assert calls == [("select", REGION_INCLUDE_TOOL), "reset_range"]
    assert app.selected_region_id is None


def test_select_region_from_dock_activates_select_tool_before_selecting() -> None:
    app = LayoutBuilder()
    app.tool_mode = _Var(REGION_INCLUDE_TOOL)
    calls = []
    app._set_selected_region_id = lambda value: calls.append(("select_region", value))
    app._sync_tool_options = lambda: calls.append(("sync", None))
    app.update_display = lambda: calls.append(("display", None))

    app._select_region_from_dock("region_a")

    assert app.tool_mode.get() == "select"
    assert calls[0] == ("select_region", "region_a")


def test_inspector_mousewheel_outside_does_not_scroll_and_unbinds() -> None:
    app = _App()
    app._bind_inspector_mouse_wheel()

    result = app._on_inspector_mouse_wheel(_Event(x_root=10, y_root=10, delta=120))

    assert result is None
    assert app.inspector_scroll_canvas.scrolls == []
    assert app.root.class_bindings == {}
    assert "InspectorWheel" not in app.inspector_scroll_canvas.bindtags()
    assert "InspectorWheel" not in app.inspector_scroll_body.bindtags()


def test_inspector_mousewheel_inside_scrolls_canvas() -> None:
    app = _App()
    app._bind_inspector_mouse_wheel()

    result = app._on_inspector_mouse_wheel(_Event(x_root=120, y_root=120, delta=120))

    assert result == "break"
    assert app.inspector_scroll_canvas.scrolls == [(-3, "units")]
    assert ("InspectorWheel", "<MouseWheel>") in app.root.class_bindings
