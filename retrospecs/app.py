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
    from retrospecs.ui import ToolbarWindow, TrayIcon

    overlay = OverlayWindow()
    shader_index = overlay.load_settings()

    toolbar = ToolbarWindow(overlay)
    overlay.set_toolbar(toolbar)

    tray = TrayIcon(overlay, toolbar)
    tray.show()

    overlay.show()
    overlay.enable_click_through()
    toolbar.show()
    toolbar.sync_position()

    overlay.set_shader(shader_index)
    overlay.start()

    return app.exec_()
