"""Separate toolbar window, system-tray icon, and resize grip."""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QApplication,
    QSystemTrayIcon, QMenu, QAction,
)
from PyQt5.QtCore import Qt, QRect, QPoint, QSize
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QIcon, QPixmap

from retrospecs.shaders import SHADERS

TOOLBAR_HEIGHT = 28


# ---------------------------------------------------------------------------
# Toolbar window
# ---------------------------------------------------------------------------

class ToolbarWindow(QWidget):
    """Floating toolbar that controls the click-through overlay.

    Drag the toolbar to move the overlay.  Shader buttons switch the
    active CRT effect.  The resize button temporarily makes the overlay
    interactive so its edges can be dragged.
    """

    def __init__(self, overlay):
        super().__init__()
        self._overlay = overlay
        self._drag_pos = None
        self._overlay_start = None
        self._toolbar_start = None

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedHeight(TOOLBAR_HEIGHT)

        self._build_ui()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 4, 2)
        layout.setSpacing(3)

        # Drag handle
        drag = QWidget(self)
        drag.setFixedWidth(12)
        drag.setCursor(Qt.SizeAllCursor)
        layout.addWidget(drag)

        # Shader buttons
        self._shader_buttons = []
        btn_font = QFont("monospace", 8)
        btn_font.setBold(True)
        for i, shader in enumerate(SHADERS):
            btn = QPushButton(shader["short"], self)
            btn.setFont(btn_font)
            btn.setFixedSize(36, 20)
            btn.setCheckable(True)
            btn.setToolTip(shader["name"] + " \u2014 " + shader["description"])
            btn.setStyleSheet(_button_style(False))
            btn.clicked.connect(
                lambda checked, idx=i: self._on_shader_click(idx)
            )
            layout.addWidget(btn)
            self._shader_buttons.append(btn)

        layout.addStretch()

        # Fullscreen toggle
        self._btn_fullscreen = QPushButton("\u2922", self)  # ⤢
        self._btn_fullscreen.setFixedSize(22, 20)
        self._btn_fullscreen.setCheckable(True)
        self._btn_fullscreen.setToolTip("Toggle fullscreen (F11)")
        self._btn_fullscreen.setStyleSheet(_ctrl_style())
        self._btn_fullscreen.clicked.connect(self._on_fullscreen_toggle)
        layout.addWidget(self._btn_fullscreen)

        # Minimize
        btn_min = QPushButton("\u2013", self)  # –
        btn_min.setFixedSize(22, 20)
        btn_min.setToolTip("Hide overlay")
        btn_min.setStyleSheet(_ctrl_style())
        btn_min.clicked.connect(self._on_minimize)
        layout.addWidget(btn_min)

        # Close
        btn_close = QPushButton("\u00d7", self)  # ×
        btn_close.setFixedSize(22, 20)
        btn_close.setToolTip("Quit RetroSpecs")
        btn_close.setStyleSheet(_ctrl_style(close=True))
        btn_close.clicked.connect(self._on_close)
        layout.addWidget(btn_close)

    # -- Public API ----------------------------------------------------------

    def set_active_shader(self, index):
        for i, btn in enumerate(self._shader_buttons):
            active = i == index
            btn.setChecked(active)
            btn.setStyleSheet(_button_style(active))

    def sync_position(self):
        """Dock the toolbar just above the overlay (or inside if no room)."""
        geo = self._overlay.geometry()
        y = geo.y() - TOOLBAR_HEIGHT - 2
        if y < 0:
            y = geo.y() + 2
        self.move(geo.x(), y)
        self.resize(geo.width(), TOOLBAR_HEIGHT)

    # -- Slots ---------------------------------------------------------------

    def _on_shader_click(self, index):
        self.set_active_shader(index)
        self._overlay.set_shader(index)

    def _on_fullscreen_toggle(self):
        self._overlay.toggle_fullscreen()
        self._btn_fullscreen.setChecked(self._overlay.is_fullscreen)

    def _on_minimize(self):
        self._overlay.hide()
        self.hide()
        grip = getattr(self._overlay, '_resize_grip', None)
        if grip:
            grip.hide()

    def _on_close(self):
        self._overlay.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            self._on_fullscreen_toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- Drag handling (moves both toolbar + overlay) ------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos()
            self._overlay_start = self._overlay.pos()
            self._toolbar_start = self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPos() - self._drag_pos
            self._overlay.move(self._overlay_start + delta)
            self.move(self._toolbar_start + delta)
            grip = getattr(self._overlay, '_resize_grip', None)
            if grip:
                grip.sync_position()
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()

    # -- Painting ------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(20, 20, 20, 200))
        p.setPen(QPen(QColor(60, 60, 60, 150), 1))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)
        p.end()


# ---------------------------------------------------------------------------
# Resize grip — small floating handle at the overlay's bottom-right corner
# ---------------------------------------------------------------------------

_GRIP_SIZE = 20


class ResizeGrip(QWidget):
    """Draggable resize grip at the bottom-right corner of the overlay."""

    def __init__(self, overlay):
        super().__init__()
        self._overlay = overlay
        self._drag_start = None
        self._start_geom = None

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(_GRIP_SIZE, _GRIP_SIZE)
        self.setCursor(Qt.SizeFDiagCursor)

    def sync_position(self):
        """Place the grip at the overlay's bottom-right corner."""
        geo = self._overlay.geometry()
        self.move(geo.right() - _GRIP_SIZE + 2, geo.bottom() - _GRIP_SIZE + 2)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor(180, 180, 180, 200), 1)
        p.setPen(pen)
        # Three diagonal grip lines
        for i in range(3):
            off = 5 + i * 5
            p.drawLine(self.width() - 3, off, off, self.height() - 3)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPos()
            self._start_geom = self._overlay.geometry()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_start and event.buttons() & Qt.LeftButton:
            delta = event.globalPos() - self._drag_start
            geo = QRect(self._start_geom)
            geo.setRight(geo.right() + delta.x())
            geo.setBottom(geo.bottom() + delta.y())
            if geo.width() >= 200 and geo.height() >= 150:
                self._overlay.setGeometry(geo)
                self.sync_position()
                toolbar = getattr(self._overlay, '_toolbar', None)
                if toolbar:
                    toolbar.sync_position()
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        event.accept()


# ---------------------------------------------------------------------------
# System-tray icon
# ---------------------------------------------------------------------------

class TrayIcon(QSystemTrayIcon):
    """Persistent tray icon for show / hide / shader selection / quit."""

    def __init__(self, overlay, toolbar, parent=None):
        # Simple coloured square icon
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(0, 180, 255))
        icon = QIcon(pixmap)
        super().__init__(icon, parent)
        self.setToolTip("RetroSpecs")

        self._overlay = overlay
        self._toolbar = toolbar

        menu = QMenu()

        show_action = menu.addAction("Show / Hide")
        show_action.triggered.connect(self._toggle_visibility)
        menu.addSeparator()

        self._shader_actions = []
        for i, shader in enumerate(SHADERS):
            action = QAction(shader["name"], menu)
            action.triggered.connect(
                lambda checked, idx=i: self._on_shader(idx)
            )
            menu.addAction(action)
            self._shader_actions.append(action)

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._on_quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _toggle_visibility(self):
        grip = getattr(self._overlay, '_resize_grip', None)
        if self._overlay.isVisible():
            self._overlay.hide()
            self._toolbar.hide()
            if grip:
                grip.hide()
        else:
            self._overlay.show()
            self._toolbar.show()
            self._toolbar.sync_position()
            if grip:
                grip.show()
                grip.sync_position()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_visibility()

    def _on_shader(self, index):
        self._overlay.set_shader(index)
        self._toolbar.set_active_shader(index)

    def _on_quit(self):
        self._overlay.close()


# ---------------------------------------------------------------------------
# Shared stylesheet helpers
# ---------------------------------------------------------------------------

def _button_style(active):
    if active:
        return (
            "QPushButton { background: rgba(0, 180, 255, 200); color: white;"
            " border: 1px solid rgba(0, 200, 255, 255); border-radius: 3px;"
            " font-size: 9px; }"
        )
    return (
        "QPushButton { background: rgba(60, 60, 60, 180); color: #aaa;"
        " border: 1px solid rgba(80, 80, 80, 180); border-radius: 3px;"
        " font-size: 9px; }"
        "QPushButton:hover { background: rgba(80, 80, 80, 200); color: white; }"
    )


def _ctrl_style(close=False):
    hover_bg = "rgba(220, 50, 50, 220)" if close else "rgba(80, 80, 80, 200)"
    return (
        "QPushButton { background: transparent; color: #aaa;"
        " border: none; font-size: 14px; }"
        "QPushButton:hover { background: %s; color: white; }" % hover_bg
    )
