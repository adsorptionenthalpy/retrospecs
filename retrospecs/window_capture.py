"""Capture from the window below ours using Qt + xprop.

Uses QScreen.grabWindow(wid, ...) to read directly from the target
window's backing pixmap.  On a composited desktop the pixmap is
maintained by the compositor regardless of occlusion, so our overlay
never appears in the capture.
"""

import re
import subprocess
import sys
import threading

import numpy as np
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage

_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")
_NUM_RE = re.compile(r"(-?\d+)")


class WindowCapture:
    """Flicker-free capture by reading another window's backing pixmap."""

    # Re-detect target every N frames (~10 s at 30 fps).
    _DETECT_INTERVAL = 300

    def __init__(self, own_window_id):
        self._own_wid = int(own_window_id)
        self._target_wid = 0
        self._target_geom = (0, 0, 0, 0)
        self._refresh_counter = 0
        self._screen = QApplication.primaryScreen()

        # Background detection state
        self._detect_lock = threading.Lock()
        self._detect_thread = None

    # -- public --------------------------------------------------------------

    def grab(self, screen_x, screen_y, width, height):
        """Return RGBA numpy array (height, width, 4) or None."""
        # Kick off background target detection when needed
        self._refresh_counter += 1
        if self._target_wid == 0 or self._refresh_counter >= self._DETECT_INTERVAL:
            self._refresh_counter = 0
            self._start_detect(screen_x, screen_y, width, height)

        if self._target_wid == 0:
            return None

        tx, ty, tw, th = self._target_geom
        local_x = screen_x - tx
        local_y = screen_y - ty

        if local_x < 0:
            width += local_x
            local_x = 0
        if local_y < 0:
            height += local_y
            local_y = 0
        width = min(width, tw - local_x)
        height = min(height, th - local_y)
        if width <= 0 or height <= 0:
            return None

        pixmap = self._screen.grabWindow(
            self._target_wid, local_x, local_y, width, height,
        )
        if pixmap.isNull():
            self._target_wid = 0
            return None

        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.constBits()
        ptr.setsize(h * w * 4)
        return np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4)).copy()

    def close(self):
        pass

    # -- background target detection -----------------------------------------

    def _start_detect(self, sx, sy, sw, sh):
        """Run _find_target in a background thread so subprocess calls
        never block the render loop."""
        if self._detect_thread is not None and self._detect_thread.is_alive():
            return  # already running
        self._detect_thread = threading.Thread(
            target=self._detect_worker, args=(sx, sy, sw, sh), daemon=True,
        )
        self._detect_thread.start()

    def _detect_worker(self, sx, sy, sw, sh):
        wid, geom = self._find_target(sx, sy, sw, sh)
        if wid:
            with self._detect_lock:
                self._target_wid = wid
                self._target_geom = geom

    def _find_target(self, sx, sy, sw, sh):
        """Return (wid, geom) of the best window below ours, or (0, None)."""
        stacking = self._get_stacking()
        if not stacking:
            return 0, None

        found_self = False
        for wid in reversed(stacking):
            if wid == self._own_wid:
                found_self = True
                continue
            if not found_self:
                continue
            geom = self._get_geometry(wid)
            if geom is None:
                continue
            wx, wy, ww, wh = geom
            if wx < sx + sw and wx + ww > sx and wy < sy + sh and wy + wh > sy:
                return wid, geom

        # Tool windows may not appear in the stacking list; fall back to
        # the largest overlapping window.
        if not found_self:
            best, best_area, best_geom = 0, 0, None
            for wid in reversed(stacking):
                if wid == self._own_wid:
                    continue
                geom = self._get_geometry(wid)
                if geom is None:
                    continue
                wx, wy, ww, wh = geom
                if wx < sx + sw and wx + ww > sx and wy < sy + sh and wy + wh > sy:
                    area = ww * wh
                    if area > best_area:
                        best, best_area, best_geom = wid, area, geom
            if best:
                return best, best_geom

        return 0, None

    @staticmethod
    def _get_stacking():
        try:
            out = subprocess.check_output(
                ["xprop", "-root", "_NET_CLIENT_LIST_STACKING"],
                stderr=subprocess.DEVNULL, timeout=2,
            ).decode()
        except Exception:
            return []
        return [int(h, 16) for h in _HEX_RE.findall(out)]

    @staticmethod
    def _get_geometry(wid):
        try:
            out = subprocess.check_output(
                ["xwininfo", "-id", hex(wid)],
                stderr=subprocess.DEVNULL, timeout=2,
            ).decode()
        except Exception:
            return None
        vals = {}
        for line in out.splitlines():
            for key in ("Absolute upper-left X:", "Absolute upper-left Y:",
                        "Width:", "Height:"):
                if key in line:
                    m = _NUM_RE.search(line.split(key, 1)[1])
                    if m:
                        vals[key] = int(m.group(1))
        try:
            return (
                vals["Absolute upper-left X:"],
                vals["Absolute upper-left Y:"],
                vals["Width:"],
                vals["Height:"],
            )
        except KeyError:
            return None
