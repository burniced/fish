from __future__ import annotations

import base64
import sys
import time
import tkinter as tk
from collections.abc import Callable

import cv2
import numpy as np

from area_selector import PixelRect
from detect import BALL_MAX, BALL_MIN, BALL_SAT, SIDE_MIN, Detector
from overlays import _LabelOverlay
from win_focus import detach_window, keep_overlay_on_top, pin_topmost_realised

MIN_DRAW = 6
RECORD_SEC = 8.0
RECORD_FPS = 6.0
CHECK_FRAMES = 32
BOX_COLOR = "#FF50FF"
PAD_X, PAD_X_MIN = 1.5, 80
PAD_Y, PAD_Y_MIN = 0.125, 24
GAINS = (1.0, 1.5, 2.0, 3.0)
YELLOWS = (1.5, 2.5)
LOCKS = (1.0, 0.0)
BALL_MN_MIN = 60
BALL_MX_MIN = 90
STATE_MARGIN = 0.3
STATE_MIN_PX = 10
GOOD_RATE = 0.85


def record(capture, stop, tick=None, seconds: float = RECORD_SEC, fps: float = RECORD_FPS):
    first = None
    shots = []
    end = time.perf_counter() + seconds
    step = 1.0 / fps
    while not stop.is_set():
        t0 = time.perf_counter()
        if t0 >= end:
            break
        try:
            frame = capture()
        except Exception:
            frame = None
        if frame is not None:
            if first is None:
                first = frame
            if frame.shape == first.shape:
                ok, buf = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                if ok:
                    shots.append(buf)
        if tick is not None:
            tick(max(0.0, end - time.perf_counter()), len(shots))
        stop.wait(max(0.0, step - (time.perf_counter() - t0)))
    return first, shots


def _zone_state(crop, box):
    bx0, by0, bx1, by1 = box
    H, W = crop.shape[:2]
    m = STATE_MARGIN * (bx1 - bx0)
    x0, x1 = max(0, int(bx0 - m)), min(W, int(bx1 + m) + 1)
    y0, y1 = max(0, int(by0)), min(H, int(by1) + 1)
    if x1 - x0 < 4 or y1 - y0 < 8:
        return None, None
    roi = crop[y0:y1, x0:x1].astype(np.int16)
    b, g, r = roi[..., 0], roi[..., 1], roi[..., 2]
    lo = np.minimum(r, g)
    hi = np.maximum(r, g)
    yellow = (lo >= 110) & (b * 20 <= lo * 11) & (np.abs(r - g) * 4 <= hi)
    green = (g >= 110) & ((g - r) * 10 >= g * 3) & ((g - b) * 10 >= g * 3)
    need = max(STATE_MIN_PX, int(0.5 * (bx1 - bx0)))
    ny, ng = int(yellow.sum()), int(green.sum())
    if max(ny, ng) < need:
        return None, None
    mask = yellow if ny > ng else green
    ys, xs = np.nonzero(mask)
    place = (
        float(np.percentile(ys, 10)) + y0, float(np.percentile(ys, 90)) + y0,
        float(np.percentile(xs, 10)) + x0, float(np.percentile(xs, 90)) + x0,
    )
    return ("yellow" if ny > ng else "green"), place


def crops_from_shots(shots, rect: PixelRect, bounds: PixelRect) -> list:
    if len(shots) > CHECK_FRAMES:
        pick = np.linspace(0, len(shots) - 1, CHECK_FRAMES).round().astype(int)
        shots = [shots[i] for i in sorted(set(pick.tolist()))]
    out = []
    for buf in shots:
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None:
            continue
        fh, fw = frame.shape[:2]
        sx, sy = fw / float(bounds.w), fh / float(bounds.h)
        bx0 = (rect.x - bounds.x) * sx
        by0 = (rect.y - bounds.y) * sy
        bx1 = bx0 + rect.w * sx
        by1 = by0 + rect.h * sy
        px = max(PAD_X_MIN, PAD_X * (bx1 - bx0))
        py = max(PAD_Y_MIN, PAD_Y * (by1 - by0))
        x0, y0 = max(0, int(bx0 - px)), max(0, int(by0 - py))
        x1, y1 = min(fw, int(bx1 + px)), min(fh, int(by1 + py))
        if x1 - x0 < 8 or y1 - y0 < 20:
            continue
        crop = np.ascontiguousarray(frame[y0:y1, x0:x1])
        box = (bx0 - x0, by0 - y0, bx1 - x0, by1 - y0)
        state, place = _zone_state(crop, box)
        out.append((crop, box, state, place))
    return out


def _ball(bgr):
    b, g, r = cv2.split(bgr)
    mn = cv2.min(cv2.min(b, g), r)
    mx = cv2.max(cv2.max(b, g), r)
    sat = cv2.subtract(mx, mn)
    white = mn.astype(np.int16) - sat.astype(np.int16) // 2
    top = float(np.percentile(white, 99.7))
    if top < BALL_MN_MIN:
        return None
    m = (white >= 0.8 * top).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    best = None
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if w < 3 or h < 3 or not (0.5 <= w / float(h) <= 2.0) or area < 0.4 * w * h:
            continue
        if best is None or area > best[4]:
            best = (x, y, w, h, area, i)
    if best is None:
        return None
    x, y, w, h, _area, i = best
    core = lab == i
    ball = {
        "size": max(w, h) * 1.15,
        "mn": float(np.percentile(mn[core], 10)),
        "mx": float(np.percentile(mx[core], 10)),
        "sat": float(np.percentile(sat[core], 90)),
    }
    if ball["mn"] < BALL_MN_MIN or ball["mx"] < BALL_MX_MIN:
        return None
    return ball


def _ball_options(crops) -> list[dict]:
    opts = [{}]
    balls = []
    for crop, (bx0, by0, bx1, by1), _state, _place in crops:
        inner = crop[max(0, int(by0)):int(by1), max(0, int(bx0)):int(bx1)]
        if inner.size:
            b = _ball(inner)
            if b is not None:
                balls.append(b)
    if len(balls) < 3:
        return opts
    mn = float(np.median([b["mn"] for b in balls]))
    mx = float(np.median([b["mx"] for b in balls]))
    sat = float(np.median([b["sat"] for b in balls]))
    s = float(np.median([b["size"] for b in balls]))
    loose = {
        "ball_min": float(max(BALL_MN_MIN, min(BALL_MIN, int(0.75 * mn)))),
        "ball_max": float(max(BALL_MX_MIN, min(BALL_MAX, int(0.8 * mx)))),
        "ball_sat": float(min(200, max(BALL_SAT, int(1.2 * sat + 10)))),
    }
    if loose != {"ball_min": float(BALL_MIN), "ball_max": float(BALL_MAX), "ball_sat": float(BALL_SAT)}:
        opts.append(loose)
    if s < 16:
        opts.append(dict(loose, erode=3.0, side_min=float(min(SIDE_MIN, max(4, int(0.6 * (s - 2)))))))
    return opts


class _Score:
    def __init__(self) -> None:
        self.seen = {"green": 0, "yellow": 0}
        self.total = {"green": 0, "yellow": 0}
        self.hits = 0

    def rate(self, state: str) -> float:
        return self.seen[state] / float(self.total[state]) if self.total[state] else 1.0

    @property
    def worst(self) -> float:
        return min(self.rate("green"), self.rate("yellow"))

    def key(self) -> tuple:
        return (round(self.worst, 4), self.hits)

    def text(self) -> str:
        parts = []
        for state in ("green", "yellow"):
            if self.total[state]:
                parts.append("%s %d/%d" % (state, self.seen[state], self.total[state]))
        return ", ".join(parts) if parts else "%d frames" % self.hits


def _judge(crops, colors: dict, yellow: float, stop, green: float = 1.0, white: float = 1.0) -> _Score | None:
    det = Detector()
    det.configure(colors or None, yellow, green, white)
    score = _Score()
    near = None
    for crop, (bx0, by0, bx1, by1), state, place in crops:
        if stop is not None and stop.is_set():
            return None
        if state is not None:
            score.total[state] += 1
        game = det.find(crop, (0, 0), near)
        near = None
        if game is None or not game.has_zone:
            continue
        w = max(4, int(game.ball_w))
        if not (bx0 - w <= game.ball_x <= bx1 + w and by0 - w <= game.ball_y <= by1 + w):
            continue
        if not (bx0 - w <= game.zone_x <= bx1 + w):
            continue
        near = (game.ball_x, game.ball_y)
        if state is not None:
            top, bot, left, right = place
            zh = game.zone_bot - game.zone_top
            if not (top - 0.5 * zh <= game.zone_y <= bot + 0.5 * zh and left - w <= game.zone_x <= right + w):
                continue
            score.seen[state] += 1
        score.hits += 1
    return score


def _options(crops, yellow: float, green: float = 1.0) -> list[tuple[int, dict]]:
    out = []
    yellows = (yellow,) + tuple(y for y in YELLOWS if y > yellow)
    gains = (green,) + tuple(g for g in GAINS if g > green)
    for bi, ball in enumerate(_ball_options(crops)):
        for gi, gain in enumerate(gains):
            for yi, yel in enumerate(yellows):
                for li, lock in enumerate(LOCKS):
                    if bi == gi == yi == li == 0:
                        continue
                    colors = dict(ball)
                    if gain != green:
                        colors["gain"] = gain
                    if yel != yellow:
                        colors["yellow"] = yel
                    if lock != 1.0:
                        colors["lock"] = lock
                    out.append((bi * 2 + gi + yi + li, colors))
    out.sort(key=lambda o: o[0])
    return out


def measure(crops: list, yellow: float, stop=None, progress=None, green: float = 1.0, white: float = 1.0) -> tuple[dict | None, bool, str]:
    total = len(crops)
    if total < 3:
        return None, False, "The recording was too short. Press the hotkey while the fishing minigame is on screen and keep fishing."
    cancelled = (None, False, "Bar color detect cancelled.")
    base = _judge(crops, {}, yellow, stop, green, white)
    if base is None:
        return cancelled
    n_green, n_yellow = base.total["green"], base.total["yellow"]
    no_yellow = "" if n_yellow else " The bar never turned yellow while recording, press the hotkey again and let the ball fall out of the zone a few times."
    if n_green + n_yellow == 0 and base.hits == 0:
        return None, False, "Couldn't see the fishing bar in the recording. Press the hotkey while the minigame is up, keep fishing, and draw the box over the whole bar."
    if n_yellow and base.worst >= GOOD_RATE:
        return None, True, "Normal colors already see your bar (%s), nothing needed changing." % base.text()
    options = _options(crops, yellow, green)
    results = []
    for k, (cost, colors) in enumerate(options):
        if progress is not None:
            progress(k + 1, len(options))
        got = _judge(crops, colors, yellow, stop, green, white)
        if got is None:
            return cancelled
        results.append((got, cost, colors))
        if got.worst >= 1.0 and got.hits >= total - 1:
            break
    if not results:
        return None, True, "Normal colors kept (%s).%s" % (base.text(), no_yellow)
    best = max(results, key=lambda r: r[0].key())[0]
    close = [r for r in results if r[0].worst >= best.worst - 0.05 and r[0].hits >= best.hits - 1]
    pick, _cost, colors = min(close, key=lambda r: r[1])
    gained = pick.worst > base.worst + 1e-6 or pick.hits >= base.hits + max(2, int(0.1 * total))
    if not gained:
        if n_yellow and base.seen["yellow"] < n_yellow:
            return None, True, "No setting could find the yellow bar better (%s). Send a clip of the minigame so it can be fixed." % base.text()
        return None, True, "The normal colors work best here (%s), nothing needed changing.%s" % (base.text(), no_yellow)
    return colors, True, "Bar colors saved: %s (normal colors: %s).%s" % (pick.text(), base.text(), no_yellow)


class RecordBanner(_LabelOverlay):
    def show(self, bounds: PixelRect, text: str) -> None:
        self._ensure(text, "#ffd27a", ("Segoe UI", 12, "bold"))
        assert self._win is not None and self._label is not None
        self._label.config(text=text)
        self._win.update_idletasks()
        w = int(self._label.winfo_reqwidth()) + 4
        h = int(self._label.winfo_reqheight()) + 2
        x = bounds.x + (bounds.w - w) // 2
        y = bounds.y + 70
        self._win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        keep_overlay_on_top(self._win)


class BarDrawer(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        frame,
        bounds: PixelRect,
        on_saved: Callable[[PixelRect], None],
        on_cancelled: Callable[[], None],
        initial: PixelRect | None = None,
    ) -> None:
        super().__init__(master)
        self.on_saved = on_saved
        self.on_cancelled = on_cancelled
        self._done = False
        self._bounds = bounds
        self._start: tuple[int, int] | None = None
        self._rect: PixelRect | None = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#000000")
        self.geometry(f"{bounds.w}x{bounds.h}+{bounds.x}+{bounds.y}")

        self._canvas = tk.Canvas(self, width=bounds.w, height=bounds.h, bg="#000000", highlightthickness=0, bd=0, cursor="crosshair")
        self._canvas.pack(fill="both", expand=True)
        shown = frame
        if shown.shape[1] != bounds.w or shown.shape[0] != bounds.h:
            shown = cv2.resize(shown, (bounds.w, bounds.h), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", shown, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        self._photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii")) if ok else None
        if self._photo is not None:
            self._canvas.create_image(0, 0, image=self._photo, anchor="nw")

        text = (
            "Fishing Bar Color Detect\n"
            "Recording done. Click and drag a box over the fishing bar (the whole bar, top to bottom)\n"
            "Enter saves, Esc cancels"
        )
        label = self._canvas.create_text(bounds.w // 2, 18, text=text, fill="#f3ece4", font=("Segoe UI", 13, "bold"), justify="center", anchor="n")
        x0, y0, x1, y1 = self._canvas.bbox(label)
        back = self._canvas.create_rectangle(x0 - 14, y0 - 10, x1 + 14, y1 + 10, fill="#211c17", outline="#c47a3a", width=2)
        self._canvas.tag_lower(back, label)

        self._box = self._canvas.create_rectangle(0, 0, 0, 0, outline=BOX_COLOR, width=2, state="hidden")
        if initial is not None:
            self._set_rect(PixelRect(initial.x - bounds.x, initial.y - bounds.y, initial.w, initial.h))

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag)
        self.bind("<Return>", lambda _e: self.save())
        self.bind("<KP_Enter>", lambda _e: self.save())
        self.bind("<space>", lambda _e: self.save())
        self.bind("<Escape>", lambda _e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        detach_window(self)
        pin_topmost_realised(self)
        self.focus_force()
        self.grab_set()

    def _set_rect(self, r: PixelRect) -> None:
        self._rect = r
        self._canvas.coords(self._box, r.x, r.y, r.x + r.w, r.y + r.h)
        self._canvas.itemconfigure(self._box, state="normal")

    def _on_press(self, event: tk.Event) -> None:
        self._start = (int(event.x), int(event.y))

    def _on_drag(self, event: tk.Event) -> None:
        if self._start is None:
            return
        bw, bh = self._bounds.w, self._bounds.h
        x = max(0, min(bw - 1, int(event.x)))
        y = max(0, min(bh - 1, int(event.y)))
        sx, sy = self._start
        if abs(x - sx) < 2 and abs(y - sy) < 2:
            return
        self._set_rect(PixelRect(min(sx, x), min(sy, y), abs(x - sx) + 1, abs(y - sy) + 1))

    def _finish(self, saved: bool) -> None:
        if self._done:
            return
        self._done = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        r = self._rect
        self.destroy()
        if sys.platform == "darwin":
            try:
                self.master.focus_force()
            except tk.TclError:
                pass
        if saved and r is not None:
            self.on_saved(PixelRect(r.x + self._bounds.x, r.y + self._bounds.y, r.w, r.h))
        else:
            self.on_cancelled()

    def save(self) -> None:
        r = self._rect
        if r is None or r.w < MIN_DRAW or r.h < MIN_DRAW:
            return
        self._finish(True)

    def cancel(self) -> None:
        self._finish(False)
