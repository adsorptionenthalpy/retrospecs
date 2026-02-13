"""X11 direct window capture via ctypes — reads from the backing pixmap
of the window below ours without hiding anything."""

import sys
import ctypes
import ctypes.util
import numpy as np

if sys.platform != "linux":
    raise ImportError("X11 capture is only available on Linux")

# ---------------------------------------------------------------------------
# Load libX11
# ---------------------------------------------------------------------------
_libname = ctypes.util.find_library("X11") or "libX11.so.6"
try:
    _x11 = ctypes.cdll.LoadLibrary(_libname)
except OSError:
    raise ImportError("libX11 not found")

# X11 types
_Display_p = ctypes.c_void_p
_Window = ctypes.c_ulong
_Atom = ctypes.c_ulong
_Bool = ctypes.c_int
_Status = ctypes.c_int
_AllPlanes = ctypes.c_ulong(0xFFFFFFFF)
_ZPixmap = 2
_XA_WINDOW = 33  # Xatom.h


# ---------------------------------------------------------------------------
# Struct definitions
# ---------------------------------------------------------------------------
class _XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong),
        ("class_", ctypes.c_int),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_masks", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


class _XImageFuncs(ctypes.Structure):
    _fields_ = [
        ("create_image", ctypes.c_void_p),
        ("destroy_image", ctypes.c_void_p),
        ("get_pixel", ctypes.c_void_p),
        ("put_pixel", ctypes.c_void_p),
        ("sub_image", ctypes.c_void_p),
        ("add_pixel", ctypes.c_void_p),
    ]


class _XImage(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("xoffset", ctypes.c_int),
        ("format", ctypes.c_int),
        ("data", ctypes.c_char_p),
        ("byte_order", ctypes.c_int),
        ("bitmap_unit", ctypes.c_int),
        ("bitmap_bit_order", ctypes.c_int),
        ("bitmap_pad", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("bytes_per_line", ctypes.c_int),
        ("bits_per_pixel", ctypes.c_int),
        ("red_mask", ctypes.c_ulong),
        ("green_mask", ctypes.c_ulong),
        ("blue_mask", ctypes.c_ulong),
        ("obdata", ctypes.c_void_p),
        ("f", _XImageFuncs),
    ]


# ---------------------------------------------------------------------------
# Function prototypes
# ---------------------------------------------------------------------------
_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XOpenDisplay.restype = _Display_p

_x11.XCloseDisplay.argtypes = [_Display_p]

_x11.XDefaultRootWindow.argtypes = [_Display_p]
_x11.XDefaultRootWindow.restype = _Window

_x11.XInternAtom.argtypes = [_Display_p, ctypes.c_char_p, _Bool]
_x11.XInternAtom.restype = _Atom

_x11.XGetWindowProperty.argtypes = [
    _Display_p, _Window, _Atom,
    ctypes.c_long, ctypes.c_long, _Bool, _Atom,
    ctypes.POINTER(_Atom),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
]
_x11.XGetWindowProperty.restype = ctypes.c_int

_x11.XFree.argtypes = [ctypes.c_void_p]

_x11.XQueryTree.argtypes = [
    _Display_p, _Window,
    ctypes.POINTER(_Window),
    ctypes.POINTER(_Window),
    ctypes.POINTER(ctypes.POINTER(_Window)),
    ctypes.POINTER(ctypes.c_uint),
]
_x11.XQueryTree.restype = _Status

_x11.XGetWindowAttributes.argtypes = [
    _Display_p, _Window, ctypes.POINTER(_XWindowAttributes),
]
_x11.XGetWindowAttributes.restype = _Status

_x11.XTranslateCoordinates.argtypes = [
    _Display_p, _Window, _Window,
    ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(_Window),
]
_x11.XTranslateCoordinates.restype = _Bool

_x11.XGetImage.argtypes = [
    _Display_p, ctypes.c_ulong,
    ctypes.c_int, ctypes.c_int,
    ctypes.c_uint, ctypes.c_uint,
    ctypes.c_ulong, ctypes.c_int,
]
_x11.XGetImage.restype = ctypes.POINTER(_XImage)

_x11.XDestroyImage.argtypes = [ctypes.POINTER(_XImage)]
_x11.XDestroyImage.restype = ctypes.c_int

# Callback type for X error handler
_XErrorHandler = ctypes.CFUNCTYPE(
    ctypes.c_int, _Display_p, ctypes.c_void_p
)

@_XErrorHandler
def _quiet_error_handler(_display, _event):
    return 0


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------
class X11DirectCapture:
    """Read pixel data from the window below ours via XGetImage.

    On a composited desktop every window has a backing pixmap maintained
    by the compositor.  XGetImage can read from it regardless of whether
    the window is obscured — so we never need to hide our overlay.
    """

    def __init__(self, own_window_id):
        # Suppress fatal X errors so a stale window ID doesn't kill us
        _x11.XSetErrorHandler(_quiet_error_handler)

        self._display = _x11.XOpenDisplay(None)
        if not self._display:
            raise RuntimeError("Cannot open X11 display")
        self._root = _x11.XDefaultRootWindow(self._display)
        self._own_wid = int(own_window_id)
        self._stacking_atom = _x11.XInternAtom(
            self._display, b"_NET_CLIENT_LIST_STACKING", False
        )
        # Get our frame window (WM reparents client into a frame)
        self._own_frame = self._get_frame_window(self._own_wid)

    # -- public --------------------------------------------------------------

    def grab(self, screen_x, screen_y, width, height):
        """Return an RGBA numpy array of the region, or None on failure."""
        target = self._find_target_window(screen_x, screen_y, width, height)
        if not target:
            return None
        return self._read_from_window(target, screen_x, screen_y, width, height)

    def close(self):
        if self._display:
            _x11.XCloseDisplay(self._display)
            self._display = None

    # -- internals -----------------------------------------------------------

    def _get_frame_window(self, wid):
        """Walk up to the direct child of root (the WM frame)."""
        current = wid
        while True:
            root_ret = _Window()
            parent_ret = _Window()
            children_ret = ctypes.POINTER(_Window)()
            nchildren = ctypes.c_uint()
            _x11.XQueryTree(
                self._display, current,
                ctypes.byref(root_ret),
                ctypes.byref(parent_ret),
                ctypes.byref(children_ret),
                ctypes.byref(nchildren),
            )
            if children_ret:
                _x11.XFree(children_ret)
            if parent_ret.value == self._root or parent_ret.value == 0:
                return current
            current = parent_ret.value

    def _get_stacking_order(self):
        """Read _NET_CLIENT_LIST_STACKING from the root window."""
        actual_type = _Atom()
        actual_format = ctypes.c_int()
        nitems = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        prop = ctypes.POINTER(ctypes.c_ubyte)()

        ret = _x11.XGetWindowProperty(
            self._display, self._root, self._stacking_atom,
            0, 4096, False, _XA_WINDOW,
            ctypes.byref(actual_type),
            ctypes.byref(actual_format),
            ctypes.byref(nitems),
            ctypes.byref(bytes_after),
            ctypes.byref(prop),
        )
        if ret != 0 or not prop or nitems.value == 0:
            return []

        # Property format 32 → each item is c_ulong after Xlib unpacking
        n = nitems.value
        arr = ctypes.cast(prop, ctypes.POINTER(ctypes.c_ulong * n)).contents
        windows = [arr[i] for i in range(n)]
        _x11.XFree(prop)
        return windows

    def _window_screen_geometry(self, wid):
        """Return (screen_x, screen_y, width, height) for a window."""
        attrs = _XWindowAttributes()
        if not _x11.XGetWindowAttributes(self._display, wid, ctypes.byref(attrs)):
            return None
        # Translate local (0,0) to root coordinates
        rx = ctypes.c_int()
        ry = ctypes.c_int()
        child = _Window()
        _x11.XTranslateCoordinates(
            self._display, wid, self._root,
            0, 0, ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(child),
        )
        return rx.value, ry.value, attrs.width, attrs.height

    def _find_target_window(self, sx, sy, sw, sh):
        """Find the topmost managed window below ours that overlaps (sx,sy,sw,sh)."""
        stacking = self._get_stacking_order()
        if not stacking:
            return None

        # Walk top-to-bottom; once we pass our own window, the first
        # overlapping window is our target.
        found_self = False
        for i in range(len(stacking) - 1, -1, -1):
            wid = stacking[i]
            if wid == self._own_wid:
                found_self = True
                continue
            if not found_self:
                continue
            geo = self._window_screen_geometry(wid)
            if geo is None:
                continue
            wx, wy, ww, wh = geo
            # Overlap test
            if wx < sx + sw and wx + ww > sx and wy < sy + sh and wy + wh > sy:
                return wid
        return None

    def _read_from_window(self, wid, sx, sy, sw, sh):
        """XGetImage a region from *wid* and return RGBA numpy array."""
        geo = self._window_screen_geometry(wid)
        if geo is None:
            return None
        wx, wy, ww, wh = geo

        # Map screen coords → window-local coords
        lx = max(sx - wx, 0)
        ly = max(sy - wy, 0)
        gw = min(sw, ww - lx)
        gh = min(sh, wh - ly)
        if gw <= 0 or gh <= 0:
            return None

        img_ptr = _x11.XGetImage(
            self._display, wid,
            lx, ly, gw, gh,
            _AllPlanes, _ZPixmap,
        )
        if not img_ptr:
            return None

        try:
            img = img_ptr.contents
            if img.bits_per_pixel not in (24, 32):
                return None
            nbytes = img.bytes_per_line * img.height
            buf = ctypes.string_at(img.data, nbytes)
        finally:
            _x11.XDestroyImage(img_ptr)

        raw = np.frombuffer(buf, dtype=np.uint8)
        if img.bits_per_pixel == 32:
            frame = raw.reshape((gh, gw, 4)).copy()
            # BGRA → RGBA
            frame[:, :, [0, 2]] = frame[:, :, [2, 0]]
            frame[:, :, 3] = 255
        else:
            # 24-bit BGR, pad to RGBA
            raw3 = raw.reshape((gh, gw, 3))
            frame = np.empty((gh, gw, 4), dtype=np.uint8)
            frame[:, :, 0] = raw3[:, :, 2]
            frame[:, :, 1] = raw3[:, :, 1]
            frame[:, :, 2] = raw3[:, :, 0]
            frame[:, :, 3] = 255

        # Pad to requested size if the grabbed region was smaller
        if gw < sw or gh < sh:
            full = np.zeros((sh, sw, 4), dtype=np.uint8)
            full[:, :, 3] = 255
            oy = max(sx - wx, 0) - (sx - wx)  # always 0 in practice
            ox = max(sy - wy, 0) - (sy - wy)
            full[:gh, :gw] = frame
            frame = full

        return frame
