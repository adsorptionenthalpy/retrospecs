"""QOpenGLWidget: continuous capture + shader rendering at target FPS.

When using the mss capture backend the overlay and toolbar windows are
briefly hidden (opacity → 0) so they don't appear in the screenshot.
The previous frame stays on the GPU texture so the user sees a smooth
image while the capture happens.
"""

import sys
import time
import ctypes

import numpy as np
from PyQt5.QtWidgets import QOpenGLWidget, QApplication
from PyQt5.QtCore import QTimer, QPoint

from OpenGL.GL import (
    glGenVertexArrays, glBindVertexArray,
    glGenBuffers, glBindBuffer, glBufferData,
    glEnableVertexAttribArray, glVertexAttribPointer,
    glGenTextures, glBindTexture, glTexImage2D, glTexSubImage2D,
    glTexParameteri, glActiveTexture,
    glCreateShader, glShaderSource, glCompileShader, glGetShaderiv,
    glGetShaderInfoLog, glCreateProgram, glAttachShader, glLinkProgram,
    glGetProgramiv, glGetProgramInfoLog, glUseProgram, glDeleteProgram,
    glDeleteShader, glGetUniformLocation, glUniform1i, glUniform1f,
    glUniform2f,
    glDrawElements, glClear, glClearColor, glViewport,
    GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_COMPILE_STATUS,
    GL_LINK_STATUS, GL_ARRAY_BUFFER, GL_ELEMENT_ARRAY_BUFFER,
    GL_STATIC_DRAW, GL_FLOAT, GL_FALSE, GL_UNSIGNED_INT,
    GL_TEXTURE_2D, GL_TEXTURE0, GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_MAG_FILTER, GL_LINEAR, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE, GL_RGBA, GL_UNSIGNED_BYTE,
    GL_TRIANGLES, GL_COLOR_BUFFER_BIT,
)

from retrospecs.shaders import VERTEX_SHADER, SHADERS

# Delay (ms) between hiding the windows and capturing the screen.
# Gives the compositor time to process the opacity change.
_CAPTURE_DELAY_MS = 20


class GLWidget(QOpenGLWidget):
    """Captures the screen below at TARGET_FPS and renders a CRT shader."""

    TARGET_FPS = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._capture = None
        self._shader_index = 0
        self._program = 0
        self._vao = 0
        self._texture = 0
        self._tex_width = 0
        self._tex_height = 0
        self._start_time = time.monotonic()
        self._pending_frame = None
        self._viewport_w = 0
        self._viewport_h = 0

        self._loc_texture = -1
        self._loc_resolution = -1
        self._loc_time = -1

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)

        # Guard against re-entrant capture when using hide/show
        self._capturing = False

    # -- Public API ----------------------------------------------------------

    def set_shader(self, index):
        if 0 <= index < len(SHADERS):
            self._shader_index = index
            if self._program:
                self.makeCurrent()
                self._build_shader()
                self.doneCurrent()
                self.update()

    def current_shader_index(self):
        return self._shader_index

    def start(self):
        """Initialise capture backend and start the render/capture loop."""
        from retrospecs.capture import ScreenCapture

        win = self.window()
        wid = int(win.winId()) if win else None
        self._capture = ScreenCapture(own_window_id=wid)

        if self._capture.is_direct:
            print("Capture: flicker-free window capture")
        else:
            print("Capture: mss screen capture (full composite)")

        self._timer.start(1000 // self.TARGET_FPS)

    def set_companion_windows(self, *qt_widgets):
        """Tell the capture backend about companion windows to hide."""
        if self._capture:
            self._capture.set_companion_windows(*qt_widgets)

    def stop(self):
        self._timer.stop()

    # -- OpenGL setup --------------------------------------------------------

    def initializeGL(self):
        glClearColor(0.0, 0.0, 0.0, 0.0)

        # Fullscreen quad: position (2) + texcoord (2)
        vertices = np.array([
            -1.0, -1.0, 0.0, 1.0,
             1.0, -1.0, 1.0, 1.0,
             1.0,  1.0, 1.0, 0.0,
            -1.0,  1.0, 0.0, 0.0,
        ], dtype=np.float32)
        indices = np.array([0, 1, 2, 2, 3, 0], dtype=np.uint32)

        self._vao = glGenVertexArrays(1)
        glBindVertexArray(self._vao)

        vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)

        ebo = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

        stride = 4 * vertices.itemsize
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(2 * vertices.itemsize))
        glBindVertexArray(0)

        self._texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self._texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)

        self._build_shader()

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)
        self._viewport_w = w
        self._viewport_h = h
        self._tex_width = 0
        self._tex_height = 0

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT)

        frame = self._pending_frame
        if frame is not None:
            self._pending_frame = None
            self._upload(frame)

        if self._program and self._tex_width > 0:
            glUseProgram(self._program)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self._texture)

            if self._loc_texture >= 0:
                glUniform1i(self._loc_texture, 0)
            if self._loc_resolution >= 0:
                glUniform2f(self._loc_resolution,
                            float(self._viewport_w), float(self._viewport_h))
            if self._loc_time >= 0:
                glUniform1f(self._loc_time, time.monotonic() - self._start_time)

            glBindVertexArray(self._vao)
            glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)

    # -- Internals -----------------------------------------------------------

    def _build_shader(self):
        if self._program:
            glDeleteProgram(self._program)
            self._program = 0

        vert = self._compile(VERTEX_SHADER, GL_VERTEX_SHADER)
        frag = self._compile(SHADERS[self._shader_index]["fragment"],
                             GL_FRAGMENT_SHADER)
        if not vert or not frag:
            return

        prog = glCreateProgram()
        glAttachShader(prog, vert)
        glAttachShader(prog, frag)
        glLinkProgram(prog)
        if not glGetProgramiv(prog, GL_LINK_STATUS):
            print("Shader link error:", glGetProgramInfoLog(prog).decode())
            glDeleteProgram(prog)
            glDeleteShader(vert)
            glDeleteShader(frag)
            return
        glDeleteShader(vert)
        glDeleteShader(frag)
        self._program = prog
        self._loc_texture = glGetUniformLocation(prog, "uTexture")
        self._loc_resolution = glGetUniformLocation(prog, "uResolution")
        self._loc_time = glGetUniformLocation(prog, "uTime")

    @staticmethod
    def _compile(source, kind):
        s = glCreateShader(kind)
        glShaderSource(s, source)
        glCompileShader(s)
        if not glGetShaderiv(s, GL_COMPILE_STATUS):
            tag = "vertex" if kind == GL_VERTEX_SHADER else "fragment"
            print("Shader compile error (%s):" % tag,
                  glGetShaderInfoLog(s).decode())
            glDeleteShader(s)
            return 0
        return s

    def _upload(self, frame):
        h, w = frame.shape[:2]
        glBindTexture(GL_TEXTURE_2D, self._texture)
        if w != self._tex_width or h != self._tex_height:
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0,
                         GL_RGBA, GL_UNSIGNED_BYTE, frame)
            self._tex_width = w
            self._tex_height = h
        else:
            glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h,
                            GL_RGBA, GL_UNSIGNED_BYTE, frame)

    _ORIGIN = QPoint(0, 0)

    def _on_timer(self):
        if self._capture is None or self._capturing:
            return

        top_left = self.mapToGlobal(self._ORIGIN)
        x, y = top_left.x(), top_left.y()
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return

        if self._capture.needs_hide:
            # mss mode: hide overlay + toolbar + grip, wait for compositor, capture
            self._capturing = True
            self._cap_region = (x, y, w, h)
            overlay = self.window()
            toolbar = getattr(overlay, '_toolbar', None)
            grip = getattr(overlay, '_resize_grip', None)

            overlay.setWindowOpacity(0.0)
            if toolbar and toolbar.isVisible():
                toolbar.setWindowOpacity(0.0)
            if grip and grip.isVisible():
                grip.setWindowOpacity(0.0)

            QApplication.processEvents()
            QTimer.singleShot(_CAPTURE_DELAY_MS, self._finish_mss_capture)
        else:
            # Window-capture mode: no hiding needed
            frame = self._capture.grab(x, y, w, h)
            if frame is not None:
                self._pending_frame = frame
            self.update()

    def _finish_mss_capture(self):
        """Called after the compositor delay — do the actual mss grab."""
        x, y, w, h = self._cap_region

        frame = self._capture.grab(x, y, w, h)

        # Restore visibility
        overlay = self.window()
        toolbar = getattr(overlay, '_toolbar', None)
        grip = getattr(overlay, '_resize_grip', None)
        overlay.setWindowOpacity(1.0)
        if toolbar:
            toolbar.setWindowOpacity(1.0)
        if grip:
            grip.setWindowOpacity(1.0)

        if frame is not None:
            self._pending_frame = frame
        self.update()
        self._capturing = False

    def cleanup(self):
        self.stop()
        if self._capture:
            self._capture.close()
