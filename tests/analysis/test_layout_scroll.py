from sdapp.analysis.ui.layout import LayoutBuilder


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
