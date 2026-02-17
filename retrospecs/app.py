"""QApplication setup with OpenGL surface format."""

import sys
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QSurfaceFormat
from PyQt5.QtCore import Qt


def main():
    # Wayland warning — X11 is the primary target for screen capture
    if sys.platform == "linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        if "QT_QPA_PLATFORM" not in os.environ:
            print(
                "Warning: Wayland detected. Screen capture works best under X11.\n"
                "Run with: QT_QPA_PLATFORM=xcb python -m retrospecs"
            )

    # macOS: screen recording permission is required for mss capture.
    # On first launch the OS will prompt; if denied, captures return black.
    if sys.platform == "darwin":
        # Ensure the app is treated as a foreground application so the
        # permission dialog can appear and the menu-bar tray icon works.
        os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")

    # Must be set before QApplication is created
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

    # Request OpenGL 3.3 core profile with alpha
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setAlphaBufferSize(8)
    fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setApplicationName("RetroSpecs")
    app.setOrganizationName("RetroSpecs")
    app.setQuitOnLastWindowClosed(False)  # tray icon keeps app alive

    from retrospecs.main_window import OverlayWindow
    from retrospecs.ui import ToolbarWindow, TrayIcon, ResizeGrip

    overlay = OverlayWindow()
    shader_index = overlay.load_settings()

    toolbar = ToolbarWindow(overlay)
    overlay.set_toolbar(toolbar)

    grip = ResizeGrip(overlay)
    overlay.set_resize_grip(grip)

    tray = TrayIcon(overlay, toolbar)
    tray.show()

    overlay.show()
    overlay.enable_click_through()
    toolbar.show()
    toolbar.sync_position()
    grip.show()
    grip.sync_position()

    # macOS: set high window level on companion windows so they
    # also float above everything (toolbar must be above overlay).
    if sys.platform == "darwin":
        from retrospecs.main_window import _set_macos_window_level
        _set_macos_window_level(toolbar, 501)
        _set_macos_window_level(grip, 501)

    overlay.set_shader(shader_index)
    overlay.start()

    # Tell the capture backend about companion windows so it can hide
    # them during screen grabs (macOS orderOut:/orderFront: cycle).
    overlay.gl_widget.set_companion_windows(toolbar, grip)

    return app.exec_()
