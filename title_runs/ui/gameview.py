"""The game inside the app. A test's game window (an X11 window: AnyPS5 opens it through SDL, under XWayland on a
Wayland desktop) is taken into the app's own window, so a run is never a stray window on the desktop and the app shows
what is running. The game's window is known by its X11 class, which AnyPS5 sets to the title ID (PPSA04263): a list of
windows taken when the view starts watching is no use, as the game's window may already be open by then, and XWayland
gives each run's window the same ID. Clicks go to the app, not the game (the game window gets an empty input shape), so
nothing the tester does can reach a run. It needs the app to be an X11 program too (app.main sets QT_QPA_PLATFORM=xcb on Linux); where
that is not so, the game keeps its own window and the view says so."""

import ctypes
import ctypes.util

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtWidgets import QLabel, QSizePolicy, QStackedLayout, QWidget

from . import theme


class ClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


class X11:
    """Just enough Xlib: the top-level windows, their names and classes, whether one still exists, and an empty input shape."""

    def __init__(self):
        self.x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
        self.ext = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xext") or "libXext.so.6")
        x = self.x11
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                 ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_uint)]
        x.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_char_p)]
        x.XFree.argtypes = [ctypes.c_void_p]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p]
        x.XGetClassHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ClassHint)]
        self.ext.XShapeCombineRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                     ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        # Xlib's default error handler ends the whole program; a window that has gone between two calls is normal here.
        handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        self._handler = handler(lambda display, event: 0)
        x.XSetErrorHandler(self._handler)
        self.display = x.XOpenDisplay(None)
        if not self.display:
            raise OSError("no X11 display")

    def children(self, window=None):
        root, parent, kids, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
        window = window or self.x11.XDefaultRootWindow(self.display)
        if not self.x11.XQueryTree(self.display, window, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(kids), ctypes.byref(n)):
            return []
        out = [kids[i] for i in range(n.value)]
        if kids:
            self.x11.XFree(kids)
        return out

    def name(self, window):
        value = ctypes.c_char_p()
        if self.x11.XFetchName(self.display, window, ctypes.byref(value)) and value.value:
            return value.value.decode(errors="replace")
        return ""

    def classes(self, window):
        """The window's WM_CLASS: its instance and class names, lower case."""
        hint = ClassHint()
        if not self.x11.XGetClassHint(self.display, window, ctypes.byref(hint)):
            return set()
        out = set()
        for pointer in (hint.res_name, hint.res_class):
            if pointer:
                out.add(ctypes.string_at(pointer).decode(errors="replace").lower())
                self.x11.XFree(pointer)
        return out

    def exists(self, window):
        attributes = ctypes.create_string_buffer(256)  # XWindowAttributes is smaller than this on every platform
        return bool(self.x11.XGetWindowAttributes(self.display, window, attributes))

    def no_input(self, window):
        """An empty input shape: the pointer goes through the window to the app around it."""
        self.ext.XShapeCombineRectangles(self.display, window, 2, 0, 0, None, 0, 0, 0)  # ShapeInput, ShapeSet, Unsorted
        self.x11.XFlush(self.display)


def embeddable():
    return QGuiApplication.platformName() == "xcb"


class GameView(QWidget):
    """Shows a placeholder until a game window appears, then the game itself: a window whose class is one of title_ids(),
    or failing that a new window named like one of names(). watch() while a test runs, unwatch() after."""

    def __init__(self, names, log=lambda text: None, parent=None, title_ids=lambda: []):
        super().__init__(parent)
        self.names, self.log, self.title_ids = names, log, title_ids
        self.layout_ = QStackedLayout(self)
        self.placeholder = theme.mark(QLabel(""), role="muted")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.layout_.addWidget(self.placeholder)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(240)
        self.x11, self.before, self.embedded, self.container, self.seen = None, set(), None, None, set()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        if embeddable():
            try:
                self.x11 = X11()
            except OSError as error:
                self.log(f"game view: {error}")
        self.idle()

    def heightForWidth(self, width):  # noqa: N802
        return width * 9 // 16

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def idle(self, text=None):
        self.placeholder.setText(text or ("The game shows here while a test runs." if self.x11 else
                                          "While a test runs, the game opens in its own window on this desktop."))

    def watch(self):
        if self.x11 is None or self.timer.isActive():
            return
        self.before = set(self.x11.children())
        self.placeholder.setText("Starting the game…")
        self.timer.start(500)

    def unwatch(self, text=None):
        self.timer.stop()
        self.release()
        self.idle(text)

    def release(self):
        if self.container is not None:
            self.layout_.removeWidget(self.container)
            self.container.deleteLater()
        self.container, self.embedded = None, None
        self.layout_.setCurrentWidget(self.placeholder)

    def tick(self):
        if self.embedded is not None:
            if not self.x11.exists(self.embedded):  # the run ended: the next run opens a new window
                self.release()
                self.placeholder.setText("Between runs…")
                self.before = set(self.x11.children())
            return
        ids = {i.lower() for i in self.title_ids() if i}
        for window in self.x11.children():
            if ids & self.x11.classes(window):
                self.embed(window, self.x11.name(window))
                return
            if window in self.before:
                continue
            name = self.x11.name(window)
            if window not in self.seen:
                self.seen.add(window)
                self.log(f"game view: new window 0x{window:x} {name!r}")
            wanted = [n.lower() for n in self.names() if n]
            if name and (any(w in name.lower() for w in wanted) or "anyps5" in name.lower()):
                self.embed(window, name)
                return

    def embed(self, window, name):
        self.x11.no_input(window)
        foreign = QWindow.fromWinId(window)
        self.container = QWidget.createWindowContainer(foreign, self)
        self.container.setFocusPolicy(Qt.NoFocus)
        self.layout_.addWidget(self.container)
        self.layout_.setCurrentWidget(self.container)
        self.embedded = window
        self.log(f"game view: showing {name!r} (0x{window:x}) inside the app")
