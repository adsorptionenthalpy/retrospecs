"""Click-through transparent overlay with CRT shader effect.

The overlay is transparent to all mouse input — clicks, scrolls, and
drags pass straight through to the windows beneath it.  A separate
ToolbarWindow provides the interactive controls.

Click-through is implemented at the OS level:
  Linux / X11  — XShapeCombineRectangles with ShapeInput (empty region)
  Windows      — WS_EX_TRANSPARENT + WS_EX_LAYERED extended style
"""

import sys
import ctypes
import ctypes.util

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QApplication
from PyQt5.QtCore import Qt, QSettings, QPoint, QSize, QRect
from PyQt5.QtGui import QPainter, QPen, QColor

from retrospecs.gl_widget import GLWidget

_EDGE_GRIP = 8  # pixels from edge for resize handles

# ---------------------------------------------------------------------------
# Platform-specific click-through helpers
# ---------------------------------------------------------------------------

def _x11_get_ancestors(x11, display, wid):
    """Return list of window IDs from *wid* up to (excluding) root."""
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XQueryTree.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
        ctypes.POINTER(ctypes.c_uint),
    ]
    x11.XQueryTree.restype = ctypes.c_int
    x11.XFree.argtypes = [ctypes.c_void_p]

    root = x11.XDefaultRootWindow(display)
    ancestors = [wid]
    current = wid
    while True:
        root_ret = ctypes.c_ulong()
        parent_ret = ctypes.c_ulong()
        children_ret = ctypes.POINTER(ctypes.c_ulong)()
        nchildren = ctypes.c_uint()
        x11.XQueryTree(
            display, current,
            ctypes.byref(root_ret), ctypes.byref(parent_ret),
            ctypes.byref(children_ret), ctypes.byref(nchildren),
        )
        if children_ret:
            x11.XFree(children_ret)
        parent = parent_ret.value
        if parent == root or parent == 0:
            break
        current = parent
        ancestors.append(current)
    return ancestors


def _set_click_through_x11(wid, enabled):
    """Use X11 Shape extension to set/clear the input shape.

    The WM may reparent the client window inside a frame, so we must
    set the empty input shape on every ancestor up to the root.
    """
    try:
        libx11_name = ctypes.util.find_library("X11") or "libX11.so.6"
        libxext_name = ctypes.util.find_library("Xext") or "libXext.so.6"
        x11 = ctypes.cdll.LoadLibrary(libx11_name)
        xext = ctypes.cdll.LoadLibrary(libxext_name)

        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]

        display = x11.XOpenDisplay(None)
        if not display:
            return

        ShapeInput = 2
        ShapeSet = 0

        xext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p,   # display
            ctypes.c_ulong,    # window
            ctypes.c_int,      # dest_kind (ShapeInput = 2)
            ctypes.c_int,      # x_off
            ctypes.c_int,      # y_off
            ctypes.c_void_p,   # rectangles (XRectangle*)
            ctypes.c_int,      # n_rects
            ctypes.c_int,      # op (ShapeSet = 0)
            ctypes.c_int,      # ordering (Unsorted = 0)
        ]
        xext.XShapeCombineMask.argtypes = [
            ctypes.c_void_p,   # display
            ctypes.c_ulong,    # window
            ctypes.c_int,      # dest_kind
            ctypes.c_int,      # x_off
            ctypes.c_int,      # y_off
            ctypes.c_ulong,    # src (Pixmap, 0 = None)
            ctypes.c_int,      # op
        ]

        ancestors = _x11_get_ancestors(x11, display, wid)

        for win in ancestors:
            if enabled:
                # Empty input shape → click-through
                xext.XShapeCombineRectangles(
                    display, win, ShapeInput,
                    0, 0, None, 0, ShapeSet, 0,
                )
            else:
                # Reset input shape to default (full window)
                xext.XShapeCombineMask(
                    display, win, ShapeInput,
                    0, 0, 0, ShapeSet,
                )

        x11.XSync(display, 0)
        x11.XCloseDisplay(display)
    except Exception as exc:
        print("X11 click-through failed:", exc)


def _set_click_through_win32(hwnd, enabled):
    """Use WS_EX_TRANSPARENT to make/unmake the window click-through."""
    try:
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000

        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
        else:
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception as exc:
        print("Win32 click-through failed:", exc)


def set_click_through(widget, enabled):
    """Platform dispatcher: make *widget* click-through or interactive."""
    wid = int(widget.winId())
    if sys.platform == "linux":
        _set_click_through_x11(wid, enabled)
    elif sys.platform == "win32":
        _set_click_through_win32(wid, enabled)


# ---------------------------------------------------------------------------
# Overlay window
# ---------------------------------------------------------------------------

class OverlayWindow(QWidget):
    """Click-through transparent overlay showing the CRT shader effect."""

    def __init__(self):
        super().__init__()
        self._toolbar = None
        self._resize_grip = None
        self._resize_mode = False
        self._resize_edge = None
        self._resize_start = None
        self._resize_geom = None
        self._fullscreen = False
        self._pre_fs_geom = None

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMinimumSize(200, 150)
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.gl_widget = GLWidget(self)
        layout.addWidget(self.gl_widget)

        self._settings = QSettings("RetroSpecs", "RetroSpecs")

    # -- Public API ----------------------------------------------------------

    def set_toolbar(self, toolbar):
        self._toolbar = toolbar

    def set_resize_grip(self, grip):
        self._resize_grip = grip

    def set_shader(self, index):
        self.gl_widget.set_shader(index)
        if self._toolbar:
            self._toolbar.set_active_shader(index)
        self._settings.setValue("shader_index", index)

    def start(self):
        self.gl_widget.start()

    def enable_click_through(self):
        """Apply OS-level click-through.  Call after show()."""
        set_click_through(self, True)

    def load_settings(self):
        """Restore window geometry and return saved shader index."""
        pos = self._settings.value("window_pos", QPoint(100, 100))
        size = self._settings.value("window_size", QSize(640, 480))
        shader = self._settings.value("shader_index", 0, type=int)
        self.move(pos)
        self.resize(size)
        return shader

    # -- Fullscreen ----------------------------------------------------------

    def toggle_fullscreen(self):
        """Toggle between windowed and full-screen overlay."""
        if self._resize_mode:
            self.toggle_resize_mode()
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self._pre_fs_geom = self.geometry()
            screen = QApplication.screenAt(self.geometry().center())
            if screen is None:
                screen = QApplication.primaryScreen()
            self.setGeometry(screen.geometry())
            if self._resize_grip:
                self._resize_grip.hide()
        else:
            if self._pre_fs_geom:
                self.setGeometry(self._pre_fs_geom)
            if self._resize_grip:
                self._resize_grip.show()
                self._resize_grip.sync_position()
        set_click_through(self, True)
        if self._toolbar:
            self._toolbar.sync_position()

    @property
    def is_fullscreen(self):
        return self._fullscreen

    # -- Resize mode ---------------------------------------------------------

    def toggle_resize_mode(self):
        """Toggle between click-through and resize-editable."""
        self._resize_mode = not self._resize_mode
        if self._resize_mode:
            set_click_through(self, False)
        else:
            set_click_through(self, True)
            self._resize_edge = None
        self.update()

    @property
    def resize_mode(self):
        return self._resize_mode

    # -- Events --------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if not self._resize_mode:
            set_click_through(self, True)
        if self._resize_grip:
            self._resize_grip.sync_position()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._resize_mode:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, False)
            pen = QPen(QColor(0, 180, 255, 200), 2)
            p.setPen(pen)
            p.drawRect(self.rect().adjusted(1, 1, -2, -2))
            p.end()

    def mousePressEvent(self, event):
        if self._resize_mode and event.button() == Qt.LeftButton:
            edge = self._detect_edge(event.pos())
            if edge:
                self._resize_edge = edge
                self._resize_start = event.globalPos()
                self._resize_geom = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_mode:
            if self._resize_edge and event.buttons() & Qt.LeftButton:
                self._apply_resize(event.globalPos())
                event.accept()
                return
            else:
                edge = self._detect_edge(event.pos())
                self.setCursor(self._edge_cursor(edge))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resize_mode:
            self._resize_edge = None
            self._resize_start = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self._resize_mode:
            self.toggle_resize_mode()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self._save_settings()
        self.gl_widget.cleanup()
        if self._toolbar:
            self._toolbar.close()
        if self._resize_grip:
            self._resize_grip.close()
        QApplication.quit()
        super().closeEvent(event)

    # -- Settings persistence ------------------------------------------------

    def _save_settings(self):
        self._settings.setValue("window_pos", self.pos())
        self._settings.setValue("window_size", self.size())
        self._settings.setValue(
            "shader_index", self.gl_widget.current_shader_index()
        )

    # -- Resize helpers ------------------------------------------------------

    def _detect_edge(self, pos):
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        e = _EDGE_GRIP
        on_left = x < e
        on_right = x > w - e
        on_top = y < e
        on_bottom = y > h - e
        if on_top and on_left:
            return "top_left"
        if on_top and on_right:
            return "top_right"
        if on_bottom and on_left:
            return "bottom_left"
        if on_bottom and on_right:
            return "bottom_right"
        if on_left:
            return "left"
        if on_right:
            return "right"
        if on_top:
            return "top"
        if on_bottom:
            return "bottom"
        return None

    @staticmethod
    def _edge_cursor(edge):
        return {
            "left": Qt.SizeHorCursor,
            "right": Qt.SizeHorCursor,
            "top": Qt.SizeVerCursor,
            "bottom": Qt.SizeVerCursor,
            "top_left": Qt.SizeFDiagCursor,
            "bottom_right": Qt.SizeFDiagCursor,
            "top_right": Qt.SizeBDiagCursor,
            "bottom_left": Qt.SizeBDiagCursor,
        }.get(edge, Qt.ArrowCursor)

    def _apply_resize(self, global_pos):
        delta = global_pos - self._resize_start
        geo = QRect(self._resize_geom)
        edge = self._resize_edge
        if "right" in edge:
            geo.setRight(geo.right() + delta.x())
        if "bottom" in edge:
            geo.setBottom(geo.bottom() + delta.y())
        if "left" in edge:
            geo.setLeft(geo.left() + delta.x())
        if "top" in edge:
            geo.setTop(geo.top() + delta.y())
        if geo.width() >= 200 and geo.height() >= 150:
            self.setGeometry(geo)
            if self._toolbar:
                self._toolbar.sync_position()
            if self._resize_grip:
                self._resize_grip.sync_position()
