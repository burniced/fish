from __future__ import annotations

import sys
from collections import deque

import tkinter as tk

from area_selector import PixelRect
from scan_outline import OUTLINE_THICKNESS
from win_focus import detach_window, force_destroy_window, keep_overlay_on_top, style_overlay_window

_CHROMA = "#01FE01"
ARROW_OUTLINE = "#000000"

X_MARKER_W = 14
X_MARKER_H = 18
X_MARKER_GAP = 2
X_ARROW_FILL = "#FF50FF"

Y_MARKER_W = 18
Y_MARKER_H = 14
Y_MARKER_GAP = 2
GREEN_ARROW_FILL = "#50FFFF"
WHITE_ARROW_FILL = "#FF50FF"

_PARK = "+-32000+-32000"


def _make_chrome_window(master: tk.Misc, w: int, h: int) -> tuple[tk.Toplevel, tk.Canvas]:
    win = tk.Toplevel(master)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=_CHROMA, highlightthickness=0, bd=0)
    try:
        if sys.platform == "win32":
            win.attributes("-transparentcolor", _CHROMA)
        elif sys.platform == "darwin":
            win.attributes("-transparent", True)
            win.configure(bg="systemTransparent")
    except tk.TclError:
        pass
    bg = "systemTransparent" if sys.platform == "darwin" else _CHROMA
    try:
        canvas = tk.Canvas(win, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
    except tk.TclError:
        canvas = tk.Canvas(win, width=w, height=h, bg=_CHROMA, highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)
    try:
        win.attributes("-disabled", True)
    except tk.TclError:
        pass
    win.geometry(f"{w}x{h}{_PARK}")
    detach_window(win)
    style_overlay_window(win)
    return win, canvas


class _Marker:
    W = H = 0

    def __init__(self, master: tk.Misc) -> None:
        self.master = master
        self._win: tk.Toplevel | None = None

    def hide(self) -> None:
        if self._win is not None:
            try:
                if self._win.winfo_exists():
                    self._win.geometry(f"{self.W}x{self.H}{_PARK}")
                    return
            except tk.TclError:
                pass
        self._win = None

    def destroy(self) -> None:
        force_destroy_window(self._win)
        self._win = None

    def _draw(self, canvas: tk.Canvas) -> None:
        raise NotImplementedError

    def _ensure(self) -> None:
        if self._win is not None:
            try:
                if self._win.winfo_exists():
                    return
            except tk.TclError:
                self._win = None
        win, canvas = _make_chrome_window(self.master, self.W, self.H)
        self._draw(canvas)
        self._win = win

    def _park(self) -> None:
        if self._win is not None:
            try:
                if self._win.winfo_exists():
                    self._win.geometry(f"{self.W}x{self.H}{_PARK}")
            except tk.TclError:
                self._win = None

    def _place(self, x: int, y: int) -> None:
        try:
            self._ensure()
            assert self._win is not None
            self._win.geometry(f"{self.W}x{self.H}+{int(x)}+{int(y)}")
            keep_overlay_on_top(self._win)
        except tk.TclError:
            self._win = None


class ZoneXMarker(_Marker):
    W, H = X_MARKER_W, X_MARKER_H

    def _draw(self, canvas: tk.Canvas) -> None:
        canvas.create_polygon(
            1, 1,
            X_MARKER_W - 1, 1,
            X_MARKER_W // 2, X_MARKER_H - 1,
            fill=X_ARROW_FILL, outline=ARROW_OUTLINE, width=1,
        )

    def update(self, scan_rect: PixelRect, local_x: int | None) -> None:
        if local_x is None:
            self._park()
            return
        mx = scan_rect.x + int(local_x) - X_MARKER_W // 2
        my = scan_rect.y - OUTLINE_THICKNESS - X_MARKER_GAP - X_MARKER_H
        self._place(mx, my)


class _LeftArrow(_Marker):
    W, H = Y_MARKER_W, Y_MARKER_H

    def __init__(self, master: tk.Misc, fill: str) -> None:
        super().__init__(master)
        self.fill = fill

    def _draw(self, canvas: tk.Canvas) -> None:
        canvas.create_polygon(
            Y_MARKER_W - 1, 1,
            Y_MARKER_W - 1, Y_MARKER_H - 1,
            1, Y_MARKER_H // 2,
            fill=self.fill, outline=ARROW_OUTLINE, width=1,
        )

    def update(self, scan_rect: PixelRect, local_y: int | None) -> None:
        if local_y is None:
            self._park()
            return
        mx = scan_rect.x + scan_rect.w + OUTLINE_THICKNESS + Y_MARKER_GAP
        my = scan_rect.y + int(local_y) - Y_MARKER_H // 2
        self._place(mx, my)


class GreenYMarkers:
    def __init__(self, master: tk.Misc) -> None:
        self._top = _LeftArrow(master, GREEN_ARROW_FILL)
        self._bottom = _LeftArrow(master, GREEN_ARROW_FILL)

    def hide(self) -> None:
        self._top.hide()
        self._bottom.hide()

    def destroy(self) -> None:
        self._top.destroy()
        self._bottom.destroy()

    def update(self, scan_rect: PixelRect, top_y: int | None, bottom_y: int | None) -> None:
        self._top.update(scan_rect, top_y)
        self._bottom.update(scan_rect, bottom_y)


class WhiteYMarker:
    def __init__(self, master: tk.Misc) -> None:
        self._arrow = _LeftArrow(master, WHITE_ARROW_FILL)

    def hide(self) -> None:
        self._arrow.hide()

    def destroy(self) -> None:
        self._arrow.destroy()

    def update(self, scan_rect: PixelRect, local_y: int | None) -> None:
        self._arrow.update(scan_rect, local_y)


class _LabelOverlay:
    def __init__(self, master: tk.Misc) -> None:
        self.master = master
        self._win: tk.Toplevel | None = None
        self._label: tk.Label | None = None

    def hide(self) -> None:
        if self._win is not None:
            try:
                if self._win.winfo_exists():
                    self._win.geometry(f"1x1{_PARK}")
                    return
            except tk.TclError:
                pass
        self._win = None
        self._label = None

    def destroy(self) -> None:
        force_destroy_window(self._win)
        self._win = None
        self._label = None

    def _ensure(self, text: str, fg: str, font: tuple) -> None:
        if self._win is not None:
            try:
                if self._win.winfo_exists():
                    return
            except tk.TclError:
                self._win = None
        win = tk.Toplevel(self.master)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#211c17", highlightthickness=0, bd=0)
        label = tk.Label(win, text=text, bg="#211c17", fg=fg, font=font, padx=6, pady=2)
        label.pack()
        try:
            win.attributes("-disabled", True)
        except tk.TclError:
            pass
        detach_window(win)
        style_overlay_window(win)
        self._win = win
        self._label = label


class FpsOverlay(_LabelOverlay):
    def update(self, scan_rect: PixelRect, fps: float | None) -> None:
        if fps is None:
            if self._win is not None:
                try:
                    if self._win.winfo_exists():
                        self._win.geometry(f"1x1{_PARK}")
                except tk.TclError:
                    self._win = None
                    self._label = None
            return
        try:
            self._ensure("FPS --", "#50FFFF", ("Consolas", 11, "bold"))
            assert self._win is not None and self._label is not None
            self._label.config(text=f"FPS {fps:.0f}")
            self._win.update_idletasks()
            w = max(64, int(self._label.winfo_reqwidth()) + 4)
            h = max(20, int(self._label.winfo_reqheight()) + 2)
            mx = scan_rect.x
            my = scan_rect.y - OUTLINE_THICKNESS - X_MARKER_GAP - h
            self._win.geometry(f"{w}x{h}+{int(mx)}+{int(my)}")
            keep_overlay_on_top(self._win)
        except tk.TclError:
            self._win = None
            self._label = None


class PerfHintOverlay(_LabelOverlay):
    HINT_WITH_OVERLAYS = "Can't keep up? Lower Task FPS or turn off Overlays."
    HINT_FPS_ONLY = "Can't keep up? Lower Task FPS in config."

    def update(self, scan_rect: PixelRect, text: str) -> None:
        self._ensure(self.HINT_WITH_OVERLAYS, "#B450B4", ("Segoe UI", 8))
        assert self._win is not None and self._label is not None
        self._label.config(text=text)
        self._win.update_idletasks()
        w = max(120, int(self._label.winfo_reqwidth()) + 4)
        h = max(16, int(self._label.winfo_reqheight()) + 2)
        fps_slot = 22
        mx = scan_rect.x
        my = scan_rect.y - OUTLINE_THICKNESS - X_MARKER_GAP - fps_slot - h - 2
        self._win.geometry(f"{w}x{h}+{int(mx)}+{int(my)}")
        keep_overlay_on_top(self._win)


class LagDetector:
    def __init__(
        self,
        *,
        window: int = 60,
        min_samples: int = 45,
        show_ratio: float = 0.7,
        hide_ratio: float = 0.3,
        lag_factor: float = 0.85,
    ) -> None:
        self._samples: deque[bool] = deque(maxlen=max(10, int(window)))
        self._min_samples = max(10, int(min_samples))
        self._show_ratio = float(show_ratio)
        self._hide_ratio = float(hide_ratio)
        self._lag_factor = float(lag_factor)
        self.showing = False

    def reset(self) -> None:
        self._samples.clear()
        self.showing = False

    def observe(self, instant_fps: float, target_fps: float) -> bool:
        if target_fps <= 1e-06 or instant_fps <= 0:
            return self.showing
        lagging = instant_fps < target_fps * self._lag_factor
        self._samples.append(lagging)
        if len(self._samples) < self._min_samples:
            return self.showing
        ratio = sum(self._samples) / len(self._samples)
        if not self.showing:
            if ratio >= self._show_ratio:
                self.showing = True
        else:
            if ratio <= self._hide_ratio:
                self.showing = False
        return self.showing
