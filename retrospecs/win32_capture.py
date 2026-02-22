"""Windows flicker-free capture using SetWindowDisplayAffinity.

Sets WDA_EXCLUDEFROMCAPTURE on our overlay and companion windows so they
are invisible to all screen-capture APIs (including mss/BitBlt).  The
windows remain visible on the physical display.

Requires Windows 10 version 2004 (build 19041) or later.  On older
versions the flag is silently ignored and capture falls back to the
hide/show mss path.
"""

import ctypes
import ctypes.util

import numpy as np
import mss

# SetWindowDisplayAffinity constants
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011

_user32 = ctypes.windll.user32


def _set_exclude_from_capture(hwnd, exclude):
    """Mark a window as excluded from (or included in) screen captures."""
    affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
    return _user32.SetWindowDisplayAffinity(int(hwnd), affinity)


class Win32Capture:
    """Flicker-free Windows capture.

    Instead of hiding our windows before each grab, we set
    WDA_EXCLUDEFROMCAPTURE so the OS compositor omits them from any
    screen-capture surface.  mss then sees only the desktop and other
    applications.
    """

    def __init__(self, own_hwnd):
        self._own_hwnd = int(own_hwnd)
        self._companion_hwnds = []
        self._mss = mss.mss()
        self._affinity_ok = False

        # Apply the exclusion to our main overlay window
        if _set_exclude_from_capture(self._own_hwnd, True):
            self._affinity_ok = True

    @property
    def needs_hide(self):
        """False when WDA_EXCLUDEFROMCAPTURE is active."""
        return not self._affinity_ok

    def set_companion_windows(self, *qt_widgets):
        """Exclude companion windows (toolbar, grip) from capture too."""
        for w in qt_widgets:
            hwnd = int(w.winId())
            _set_exclude_from_capture(hwnd, True)
            self._companion_hwnds.append(hwnd)

    def grab(self, x, y, width, height):
        """Capture a screen region.  Returns RGBA numpy array or None."""
        if width <= 0 or height <= 0:
            return None

        monitor = {"left": x, "top": y, "width": width, "height": height}
        try:
            shot = self._mss.grab(monitor)
        except Exception:
            return None

        w, h = shot.width, shot.height
        if w <= 0 or h <= 0:
            return None

        frame = np.frombuffer(shot.raw, dtype=np.uint8).reshape(
            (h, w, 4)
        ).copy()
        # BGRA → RGBA
        frame[:, :, [0, 2]] = frame[:, :, [2, 0]]
        return frame

    def close(self):
        # Restore normal display affinity
        _set_exclude_from_capture(self._own_hwnd, False)
        for hwnd in self._companion_hwnds:
            _set_exclude_from_capture(hwnd, False)
        if self._mss:
            self._mss.close()
