"""Screen capture — mss full-screen capture with window-capture fallback.

Two capture modes:

*  ``screen`` (default) — uses the ``mss`` library to grab the full
   composited desktop.  The overlay and toolbar must be hidden first
   (``needs_hide`` is True) so they don't appear in the capture.

*  ``window`` (Linux only, automatic) — uses ``WindowCapture`` to read
   from the backing pixmap of the window directly below ours.  This is
   flicker-free (``needs_hide`` is False) because the compositor's
   backing store excludes our overlay.
"""

import sys
import numpy as np
import mss


class ScreenCapture:
    """Captures the screen region behind the overlay window."""

    def __init__(self, own_window_id=None):
        self._qt_cap = None
        self._mss = None

        # Try flicker-free window capture on Linux first
        if own_window_id and sys.platform == "linux":
            try:
                from retrospecs.window_capture import WindowCapture
                self._qt_cap = WindowCapture(own_window_id)
            except Exception as exc:
                print("Window capture unavailable (%s), using mss" % exc)

        if self._qt_cap is None:
            self._mss = mss.mss()

    @property
    def needs_hide(self):
        """True when the overlay must be hidden during capture (mss mode)."""
        return self._qt_cap is None

    @property
    def is_direct(self):
        """True when using flicker-free window capture."""
        return self._qt_cap is not None

    def grab(self, x, y, width, height):
        """Capture a screen region and return an RGBA numpy array, or None."""
        if width <= 0 or height <= 0:
            return None

        if self._qt_cap is not None:
            frame = self._qt_cap.grab(x, y, width, height)
            if frame is not None:
                return frame

        return self._mss_grab(x, y, width, height)

    def _mss_grab(self, x, y, width, height):
        if self._mss is None:
            self._mss = mss.mss()
        monitor = {"left": x, "top": y, "width": width, "height": height}
        try:
            shot = self._mss.grab(monitor)
        except Exception:
            return None
        # Use actual captured dimensions — may differ from requested
        # due to DPI scaling or screen-edge clipping.
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
        if self._qt_cap:
            self._qt_cap.close()
        if self._mss:
            self._mss.close()
