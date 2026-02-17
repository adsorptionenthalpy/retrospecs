"""macOS screen capture — flicker-free using CGWindowListCreateImageFromArray.

Captures the desktop *excluding* our own application windows by:
1. Querying all on-screen windows via CGWindowListCopyWindowInfo
2. Filtering out windows belonging to our process (by PID)
3. Building a CFArray of the remaining CGWindowIDs
4. Passing that array to CGWindowListCreateImageFromArray

This avoids any hide/show cycle — the overlay stays visible at all times
while the capture sees only the desktop and other applications' windows.

Requires the Screen Recording permission (macOS 10.15+).  On 10.13-10.14
it works without a permission prompt.

Uses ctypes to call CoreGraphics and CoreFoundation directly — no
PyObjC dependency.
"""

import ctypes
import ctypes.util
import os

import numpy as np


# ---------------------------------------------------------------------------
# CoreGraphics + CoreFoundation bindings via ctypes
# ---------------------------------------------------------------------------

def _load_frameworks():
    """Load and return (CG, CF, CGRect) ctypes handles."""
    cg_path = ctypes.util.find_library("CoreGraphics")
    cf_path = ctypes.util.find_library("CoreFoundation")
    if not cg_path or not cf_path:
        raise OSError("Could not find CoreGraphics or CoreFoundation")

    CG = ctypes.cdll.LoadLibrary(cg_path)
    CF = ctypes.cdll.LoadLibrary(cf_path)

    class CGRect(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_double),
            ("y", ctypes.c_double),
            ("width", ctypes.c_double),
            ("height", ctypes.c_double),
        ]

    # --- CGWindowListCreateImage (fallback) ---
    CG.CGWindowListCreateImage.argtypes = [
        CGRect, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
    ]
    CG.CGWindowListCreateImage.restype = ctypes.c_void_p

    # --- CGWindowListCreateImageFromArray ---
    CG.CGWindowListCreateImageFromArray.argtypes = [
        CGRect, ctypes.c_void_p, ctypes.c_uint32,
    ]
    CG.CGWindowListCreateImageFromArray.restype = ctypes.c_void_p

    # --- CGWindowListCopyWindowInfo ---
    CG.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    CG.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p

    # --- CGImage accessors ---
    CG.CGImageGetWidth.argtypes = [ctypes.c_void_p]
    CG.CGImageGetWidth.restype = ctypes.c_size_t
    CG.CGImageGetHeight.argtypes = [ctypes.c_void_p]
    CG.CGImageGetHeight.restype = ctypes.c_size_t
    CG.CGImageGetBytesPerRow.argtypes = [ctypes.c_void_p]
    CG.CGImageGetBytesPerRow.restype = ctypes.c_size_t

    CG.CGImageGetDataProvider.argtypes = [ctypes.c_void_p]
    CG.CGImageGetDataProvider.restype = ctypes.c_void_p
    CG.CGDataProviderCopyData.argtypes = [ctypes.c_void_p]
    CG.CGDataProviderCopyData.restype = ctypes.c_void_p

    # --- CFData ---
    CF.CFDataGetLength.argtypes = [ctypes.c_void_p]
    CF.CFDataGetLength.restype = ctypes.c_long
    CF.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
    CF.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_uint8)

    # --- CFRelease ---
    CF.CFRelease.argtypes = [ctypes.c_void_p]
    CF.CFRelease.restype = None

    # --- CFArray ---
    CF.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    CF.CFArrayGetCount.restype = ctypes.c_long

    CF.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    CF.CFArrayGetValueAtIndex.restype = ctypes.c_void_p

    # CFArrayCreate(allocator, values, numValues, callBacks)
    CF.CFArrayCreate.argtypes = [
        ctypes.c_void_p,                          # allocator (NULL)
        ctypes.POINTER(ctypes.c_void_p),           # values
        ctypes.c_long,                             # numValues
        ctypes.c_void_p,                           # callBacks
    ]
    CF.CFArrayCreate.restype = ctypes.c_void_p

    # --- CFDictionary ---
    CF.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    CF.CFDictionaryGetValue.restype = ctypes.c_void_p

    # --- CFNumber ---
    # CFNumberGetValue(number, theType, valuePtr)
    CF.CFNumberGetValue.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
    ]
    CF.CFNumberGetValue.restype = ctypes.c_bool

    # --- CFString constants (loaded at runtime) ---
    # We need kCGWindowNumber and kCGWindowOwnerPID
    # These are CFStringRef globals exported by CoreGraphics.
    CG.kCGWindowNumber = ctypes.c_void_p.in_dll(CG, "kCGWindowNumber")
    CG.kCGWindowOwnerPID = ctypes.c_void_p.in_dll(CG, "kCGWindowOwnerPID")

    # --- CFNumber for CGWindowID (used in CFArray for CreateImageFromArray) ---
    # CGWindowListCreateImageFromArray expects a CFArray of CGWindowID (uint32)
    # packed as CFNumberRef values.
    CF.CFNumberCreate.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
    ]
    CF.CFNumberCreate.restype = ctypes.c_void_p

    return CG, CF, CGRect


# CoreGraphics constants
kCGWindowListOptionOnScreenOnly = (1 << 0)
kCGWindowImageBoundsIgnoreFraming = (1 << 0)
kCGWindowImageNominalResolution = (1 << 4)
kCGNullWindowID = 0

# CFNumber type constants
kCFNumberSInt32Type = 3
kCFNumberSInt64Type = 4
kCFNumberIntType = 7

# kCGWindowImageDefault
kCGWindowImageDefault = 0

# kCFAllocatorDefault
kCFAllocatorDefault = None


class MacOSCapture:
    """macOS screen capture that excludes our own windows from the capture.

    Uses CGWindowListCopyWindowInfo to enumerate all on-screen windows,
    filters out windows belonging to our PID, then captures only the
    remaining windows via CGWindowListCreateImageFromArray.

    No hide/show cycle is needed — the overlay stays visible at all times.
    ``needs_hide`` is False.
    """

    def __init__(self, own_window_id):
        self._own_wid = int(own_window_id)
        self._CG, self._CF, self._CGRect = _load_frameworks()
        self._our_pid = os.getpid()

    def set_companion_windows(self, *qt_widgets):
        """Not needed for the PID-exclusion approach, but kept for API compat."""
        pass

    def grab(self, x, y, width, height):
        """Capture desktop excluding our own windows.  Returns RGBA or None."""
        CG = self._CG
        CF = self._CF

        # 1. Get all on-screen windows
        window_list = CG.CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
        if not window_list:
            return None

        try:
            window_ids = self._filter_window_ids(window_list)
        finally:
            CF.CFRelease(window_list)

        if not window_ids:
            return None

        # 2. Build CFArray of CGWindowIDs (as CGWindowID = uint32_t values)
        #    CGWindowListCreateImageFromArray expects a CFArrayRef of
        #    CGWindowID values stored as raw pointer-sized integers.
        n = len(window_ids)
        c_array = (ctypes.c_void_p * n)()
        for i, wid in enumerate(window_ids):
            # CGWindowID is uint32 — store directly as pointer value
            c_array[i] = ctypes.c_void_p(wid)

        # Use kCFTypeArrayCallBacks = NULL for raw integer storage
        cf_array = CF.CFArrayCreate(
            kCFAllocatorDefault,
            ctypes.cast(c_array, ctypes.POINTER(ctypes.c_void_p)),
            n,
            None,  # NULL callbacks — raw pointer values, not CF objects
        )
        if not cf_array:
            return None

        try:
            # 3. Capture image from only the filtered windows
            rect = self._CGRect(float(x), float(y),
                                float(width), float(height))

            cg_image = CG.CGWindowListCreateImageFromArray(
                rect, cf_array,
                kCGWindowImageBoundsIgnoreFraming | kCGWindowImageNominalResolution,
            )
        finally:
            CF.CFRelease(cf_array)

        if not cg_image:
            return None

        try:
            return self._decode_image(cg_image)
        finally:
            CF.CFRelease(cg_image)

    def _filter_window_ids(self, window_list):
        """Extract window IDs from the info list, excluding our own PID."""
        CG = self._CG
        CF = self._CF
        our_pid = self._our_pid

        count = CF.CFArrayGetCount(window_list)
        result = []

        for i in range(count):
            info = CF.CFArrayGetValueAtIndex(window_list, i)
            if not info:
                continue

            # Get kCGWindowOwnerPID
            pid_ref = CF.CFDictionaryGetValue(
                info, CG.kCGWindowOwnerPID.value)
            if not pid_ref:
                continue

            pid_val = ctypes.c_int(0)
            if not CF.CFNumberGetValue(
                    pid_ref, kCFNumberSInt32Type,
                    ctypes.byref(pid_val)):
                continue

            if pid_val.value == our_pid:
                continue  # Skip our own windows

            # Get kCGWindowNumber
            wid_ref = CF.CFDictionaryGetValue(
                info, CG.kCGWindowNumber.value)
            if not wid_ref:
                continue

            wid_val = ctypes.c_int(0)
            if not CF.CFNumberGetValue(
                    wid_ref, kCFNumberSInt32Type,
                    ctypes.byref(wid_val)):
                continue

            if wid_val.value > 0:
                result.append(wid_val.value)

        return result

    def _decode_image(self, cg_image):
        """Decode a CGImageRef into an RGBA numpy array."""
        CG = self._CG
        CF = self._CF

        w = CG.CGImageGetWidth(cg_image)
        h = CG.CGImageGetHeight(cg_image)
        if w <= 0 or h <= 0:
            return None

        bpr = CG.CGImageGetBytesPerRow(cg_image)

        provider = CG.CGImageGetDataProvider(cg_image)
        if not provider:
            return None

        data_ref = CG.CGDataProviderCopyData(provider)
        if not data_ref:
            return None

        try:
            length = CF.CFDataGetLength(data_ref)
            ptr = CF.CFDataGetBytePtr(data_ref)
            buf = np.ctypeslib.as_array(ptr, shape=(length,)).copy()
        finally:
            CF.CFRelease(data_ref)

        if bpr == w * 4:
            frame = buf[:h * w * 4].reshape((h, w, 4))
        else:
            raw = buf[:h * bpr].reshape((h, bpr))
            frame = raw[:, :w * 4].reshape((h, w, 4)).copy()

        # BGRA -> RGBA
        frame[:, :, [0, 2]] = frame[:, :, [2, 0]]
        return frame

    def close(self):
        pass
