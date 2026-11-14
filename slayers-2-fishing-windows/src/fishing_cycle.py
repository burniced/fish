from __future__ import annotations

import time
from typing import Any, Callable

import cv2
import mss
import numpy as np

from advanced_settings import DEFAULT_ADVANCED
from area_selector import DEFAULT_SCAN_AREA, FracRect, PixelRect
from input_actions import (
    click_point,
    hold_click_point,
    key_down,
    key_up,
    press_point,
    release_point,
    hold_keys,
    sleep_interruptible,
    tap_key,
)
from mouse_control import LeftClickController
from point_selector import FracPoint
from roblox_geo import rect_to_screen, resolve_origin, roblox_client_rect
from detect import Detector
from track_control import TrackController
from win_focus import find_roblox_hwnd, focus_roblox

AbortFn = Callable[[], bool]
StatusFn = Callable[[str], None]
OverlayFn = Callable[
    [PixelRect, int | None, int | None, int | None, int | None, float | None, bool],
    None,
]

POINT_KEYS = ("cast", "collect")

_MSS = getattr(mss, "MSS", None) or mss.mss

cv2.setNumThreads(1)


def _timing(cfg: dict, key: str) -> float:
    try:
        return float((cfg.get("advanced") or {})[key])
    except (KeyError, TypeError, ValueError):
        return float(DEFAULT_ADVANCED.get(key, 0.0))


def _pt(cfg: dict, key: str) -> FracPoint:
    pts = cfg.get("points") or {}
    raw = pts.get(key) or {}
    return FracPoint(float(raw.get("x", 0.5)), float(raw.get("y", 0.5)))


def scan_area_from_cfg(cfg: dict) -> FracRect:
    sa = cfg.get("scan_area") or {}
    return FracRect(
        float(sa.get("x", DEFAULT_SCAN_AREA.x)),
        float(sa.get("y", DEFAULT_SCAN_AREA.y)),
        float(sa.get("w", DEFAULT_SCAN_AREA.w)),
        float(sa.get("h", DEFAULT_SCAN_AREA.h)),
    )


def scan_rect_screen(cfg: dict) -> PixelRect:
    fr = scan_area_from_cfg(cfg)
    return rect_to_screen(fr.x, fr.y, fr.w, fr.h, resolve_origin())


def cast_point_set(cfg: dict) -> bool:
    raw = (cfg.get("points") or {}).get("cast") or {}
    return "x" in raw and "y" in raw


def _focus(should_abort: AbortFn, set_status: StatusFn) -> bool:
    set_status("Focusing Roblox...")
    for _ in range(6):
        if should_abort():
            return False
        if focus_roblox():
            return not sleep_interruptible(0.3, should_abort)
        if sleep_interruptible(0.15, should_abort):
            return False
    if find_roblox_hwnd() is None:
        set_status("Roblox window not found.")
        return False
    set_status("Roblox isn't in front, carrying on anyway...")
    return not sleep_interruptible(0.3, should_abort)


def run_cast(cfg: dict[str, Any], should_abort: AbortFn, set_status: StatusFn) -> bool:
    set_status("Casting...")
    if should_abort():
        return False
    if click_point(
        _pt(cfg, "cast"),
        settle_s=_timing(cfg, "cast_settle_sec"),
        should_abort=should_abort,
    ):
        return False
    return not sleep_interruptible(_timing(cfg, "cast_after_sec"), should_abort)


VISUAL_POLL_SEC = 0.03


def _visual_collect(cfg: dict[str, Any], should_abort: AbortFn, set_status: StatusFn, t_visible: Callable[[], bool | None]) -> bool:
    hold_s = _timing(cfg, "collect_hold_sec")
    gone_s = max(0.2, _timing(cfg, "visual_gone_sec"))
    cycle_s = max(0.3, _timing(cfg, "visual_hold_sec"))
    gap_s = max(0.03, _timing(cfg, "visual_release_sec"))
    read_s = max(0.05, _timing(cfg, "visual_read_sec"))
    full_s = max(0.0, _timing(cfg, "visual_full_sec"))
    swing_s = max(gone_s, _timing(cfg, "visual_swing_sec"))
    miss_s = max(0.0, _timing(cfg, "visual_miss_sec"))
    use_t = bool(cfg.get("collect_hold_t"))
    point = _pt(cfg, "collect")
    what = "T" if use_t else "click"

    def press() -> None:
        if use_t:
            key_down("t")
        else:
            press_point(point)

    def release() -> None:
        if use_t:
            key_up("t")
        else:
            release_point()

    start = time.perf_counter()
    end = start + max(hold_s + gone_s, _timing(cfg, "visual_max_sec"))
    set_status("Visual T collect: reading the collect prompt...")
    held = ever = False
    held_at = hold_from = last_seen = start
    wait_s = max(0.2, _timing(cfg, "visual_start_sec"))
    seen, read_at = bool(t_visible()), time.perf_counter()
    miss_from = None if seen else read_at
    try:
        while not should_abort():
            now = time.perf_counter()
            if now - read_at >= read_s:
                read_at = now
                got = t_visible()
                now = time.perf_counter()
                if got is not None:
                    seen = bool(got)
                    if seen:
                        miss_from = None
                    elif miss_from is None:
                        miss_from = now
            if seen:
                last_seen = now
                if not held:
                    set_status(f"Visual T collect: prompt text {'back' if ever else 'read'}, holding {what}...")
                    press()
                    held = ever = True
                    held_at = hold_from = time.perf_counter()
                elif now - held_at >= cycle_s:
                    set_status(f"Visual T collect: text still there, holding again {what}...")
                    release()
                    if sleep_interruptible(gap_s, should_abort):
                        return False
                    press()
                    held_at = hold_from = time.perf_counter()
            elif held and miss_from is not None and now - miss_from >= miss_s:
                held_for = miss_from - hold_from
                release()
                held = False
                if held_for >= full_s:
                    wait_s = gone_s
                    set_status("Visual T collect: text gone, making sure...")
                else:
                    wait_s = swing_s
                    set_status(f"Visual T collect: fish swung out, waiting up to {swing_s:.0f}s for the text...")
            if not held and now - last_seen >= wait_s:
                if ever:
                    return True
                set_status(f"Visual T collect: no prompt text read, normal {hold_s:.1f}s hold instead...")
                press()
                try:
                    return not sleep_interruptible(hold_s, should_abort)
                finally:
                    release()
            if now >= end:
                set_status("Visual T collect: text still read, moving on.")
                return True
            time.sleep(VISUAL_POLL_SEC)
        return False
    finally:
        if held:
            release()


def run_collect(cfg: dict[str, Any], should_abort: AbortFn, set_status: StatusFn, t_visible: Callable[[], bool | None] | None = None) -> bool:
    hold_s = _timing(cfg, "collect_hold_sec")
    if should_abort():
        return False
    focus_roblox()
    if cfg.get("t_visual") and t_visible is not None:
        if not _visual_collect(cfg, should_abort, set_status, t_visible):
            return False
    elif cfg.get("collect_hold_t"):
        set_status(f"Collecting fish (holding T {hold_s:.1f}s)...")
        if tap_key("t", hold_s=hold_s, should_abort=should_abort):
            return False
    else:
        set_status(f"Collecting fish ({hold_s:.1f}s hold)...")
        if hold_click_point(_pt(cfg, "collect"), hold_s=hold_s, should_abort=should_abort):
            return False
    return not sleep_interruptible(_timing(cfg, "after_collect_sec"), should_abort)


MOVE_KEYS = ("w", "a", "s", "d")


def merge_move(raw: Any, legacy_key: Any = None, legacy_sec: Any = None) -> dict[str, dict[str, Any]]:
    out = {k: {"on": k == "w", "sec": 0.5} for k in MOVE_KEYS}
    legacy = str(legacy_key or "").strip().lower()
    if not isinstance(raw, dict) and legacy in MOVE_KEYS:
        for k in MOVE_KEYS:
            out[k]["on"] = k == legacy
        try:
            out[legacy]["sec"] = max(0.0, float(legacy_sec))
        except (TypeError, ValueError):
            pass
    if isinstance(raw, dict):
        for k in MOVE_KEYS:
            v = raw.get(k)
            if not isinstance(v, dict):
                continue
            out[k]["on"] = bool(v.get("on"))
            try:
                out[k]["sec"] = max(0.0, float(v.get("sec", out[k]["sec"])))
            except (TypeError, ValueError):
                pass
    return out


def run_move(cfg: dict[str, Any], should_abort: AbortFn, set_status: StatusFn) -> bool:
    if not cfg.get("move_enabled") or should_abort():
        return not should_abort()
    keys = {k: v["sec"] for k, v in merge_move(cfg.get("move")).items() if v["on"] and v["sec"] > 0}
    if not keys:
        return True
    focus_roblox()
    set_status(f"Moving (holding {'+'.join(k.upper() for k in keys)})...")
    if hold_keys(keys, should_abort=should_abort):
        return False
    return not should_abort()


def _grab(sct, x: int, y: int, w: int, h: int) -> "np.ndarray":
    w, h = max(1, int(w)), max(1, int(h))
    shot = sct.grab({"left": int(x), "top": int(y), "width": w, "height": h})
    frame = np.asarray(shot, dtype=np.uint8)[:, :, :3]
    if frame.shape[0] != h or frame.shape[1] != w:
        frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(frame)


def grab_roblox() -> "np.ndarray | None":
    r = roblox_client_rect()
    if r is None:
        return None
    with _MSS() as sct:
        return _grab(sct, r.x, r.y, r.w, r.h)


_fail_streak = 0


def reset_rod(
    cfg: dict,
    should_abort: AbortFn,
    set_status: StatusFn,
    why: str,
    presses: int = 2,
) -> None:
    key = str(cfg.get("rod_key") or "").strip().lower()
    if not key:
        return
    if presses == 1:
        set_status(f"{why}, rod key once ({key.upper()})...")
    else:
        set_status(f"{why}, rod off/on ({key.upper()})...")
    focus_roblox()
    hold = _timing(cfg, "key_hold_sec")
    for _ in range(presses):
        if tap_key(key, hold_s=hold, should_abort=should_abort):
            return
        if sleep_interruptible(0.7, should_abort):
            return


def _reset_rod_after_fail(cfg: dict, should_abort: AbortFn, set_status: StatusFn, why: str) -> None:
    global _fail_streak
    _fail_streak += 1
    if _fail_streak > 1:
        why = f"{why} ({_fail_streak} in a row)"
    reset_rod(cfg, should_abort, set_status, why=why, presses=1)


SEARCH_PAD_X = 1.5
SEARCH_PAD_X_MIN = 80
SEARCH_PAD_Y = 0.125
SEARCH_PAD_Y_MIN = 24

ERROR_GIVE_UP_SEC = 5.0
IDLE_FRAME_SEC = 1.0 / 15.0


def _search_rect(sct, rect: PixelRect) -> PixelRect:
    pad_x = max(SEARCH_PAD_X_MIN, int(SEARCH_PAD_X * rect.w))
    pad_y = max(SEARCH_PAD_Y_MIN, int(SEARCH_PAD_Y * rect.h))
    vs = sct.monitors[0]
    x0 = max(int(vs["left"]), rect.x - pad_x)
    y0 = max(int(vs["top"]), rect.y - pad_y)
    x1 = min(int(vs["left"]) + int(vs["width"]), rect.x + rect.w + pad_x)
    y1 = min(int(vs["top"]) + int(vs["height"]), rect.y + rect.h + pad_y)
    return PixelRect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def _in_box(rect: PixelRect, game) -> bool:
    w = max(4, int(game.ball_w))
    return (rect.x - w <= game.ball_x <= rect.x + rect.w + w
            and rect.y - w <= game.ball_y <= rect.y + rect.h + w)


def _roi_for(search: PixelRect, game) -> tuple[int, int, int, int]:
    w = max(4, int(game.ball_w))
    left = max(search.x, int(game.ball_x - 3 * w))
    right = min(search.x + search.w, int(game.ball_x + 3 * w))
    return left, search.y, max(1, right - left), search.h


def _roi_inside(search: PixelRect, roi) -> bool:
    x, y, w, h = roi
    return (y == search.y and h == search.h
            and search.x <= x and x + w <= search.x + search.w)


def _same_game(a, b) -> bool:
    if not (a.has_zone and b.has_zone):
        return False
    w = max(4, a.ball_w)
    ha, hb = a.zone_bot - a.zone_top, b.zone_bot - b.zone_top
    return (abs(a.ball_x - b.ball_x) <= w
            and abs(a.zone_x - b.zone_x) <= w
            and abs(ha - hb) <= max(4, 0.3 * ha))


def run_minigame(
    cfg: dict[str, Any],
    scanner: Detector,
    tracker: TrackController,
    click: LeftClickController,
    should_abort: AbortFn,
    set_status: StatusFn,
    *,
    queue_overlay: OverlayFn | None = None,
    lag_observe: Callable[[float, float], bool] | None = None,
) -> bool:
    global _fail_streak
    target_fps = max(5.0, _timing(cfg, "task_fps"))
    frame_budget = 1.0 / target_fps
    poll = _timing(cfg, "poll_sec")
    adv = cfg.get("advanced") or {}
    tracker.configure(adv)
    lost_timeout = max(0.2, _timing(cfg, "lost_timeout_s"))
    start_hits = max(2, int(round(_timing(cfg, "start_confirm_frames"))))
    start_deadline = time.perf_counter() + _timing(cfg, "wait_minigame_start_sec")
    end_deadline = time.perf_counter() + _timing(cfg, "wait_minigame_end_sec")

    click.release()
    set_status("Waiting for minigame (white square)...")
    started = False
    hits = 0
    last_game = None
    near = None
    roi = None
    last_seen = 0.0
    fps_ema = 0.0
    err_since = 0.0

    with _MSS() as sct:
        while not should_abort():
            t0 = time.perf_counter()
            try:
                rect = scan_rect_screen(cfg)
                search = _search_rect(sct, rect)
                full = None
                if roi is None:
                    frame = _grab(sct, search.x, search.y, search.w, search.h)
                    off = (search.x, search.y)
                elif _roi_inside(search, roi):
                    full = _grab(sct, search.x, search.y, search.w, search.h)
                    sx = roi[0] - search.x
                    frame = np.ascontiguousarray(full[:, sx:sx + roi[2]])
                    off = (roi[0], roi[1])
                else:
                    frame = _grab(sct, *roi)
                    off = (roi[0], roi[1])
                game = scanner.find(frame, off, near)
                now = time.perf_counter()
                if game is None and roi is not None:
                    frame = full if full is not None else _grab(sct, search.x, search.y, search.w, search.h)
                    off = (search.x, search.y)
                    game = scanner.find(frame, off, near)
                    now = time.perf_counter()
                if game is not None and not _in_box(rect, game) and (not started or not game.has_zone):
                    game = None

                mid_x = green_top = green_bot = white_y = None
                if game is not None:
                    mid_x = int(game.ball_x) - rect.x
                    white_y = int(game.ball_y) - rect.y
                    if game.has_zone:
                        green_top = int(game.zone_top) - rect.y
                        green_bot = int(game.zone_bot) - rect.y

                if not started:
                    if game is not None and (last_game is None or _same_game(game, last_game)):
                        hits += 1
                        if hits >= start_hits:
                            _fail_streak = 0
                            started = True
                            tracker.start(game.ball_y, game.zone_y, game.ball_h, now)
                            near = (game.ball_x, game.ball_y)
                            roi = _roi_for(search, game)
                            last_seen = now
                            end_deadline = now + _timing(cfg, "wait_minigame_end_sec")
                            set_status("Minigame: tracking (ball %dpx)..." % game.ball_h)
                    else:
                        hits = 1 if game is not None else 0
                    last_game = game
                    if not started and now >= start_deadline:
                        set_status("Fail cast: no minigame, restarting.")
                        click.release()
                        _reset_rod_after_fail(cfg, should_abort, set_status, "No minigame")
                        return False
                else:
                    if game is None:
                        if now - last_seen > lost_timeout:
                            set_status("Minigame done, ball gone.")
                            click.release()
                            return True
                        if now - last_seen > 0.3:
                            click.release()
                    else:
                        last_seen = now
                        near = (game.ball_x, game.ball_y)
                        roi = _roi_for(search, game)
                        tracker.observe(game.ball_y, game.ball_h, game.zone_top, game.zone_y, now)
                        hold = tracker.decide(now)
                        click.set(bool(hold))
                    if now >= end_deadline:
                        set_status("Minigame timeout, collecting anyway.")
                        click.release()
                        return True

                show_hint = False
                work_elapsed = time.perf_counter() - t0
                work_fps = 1.0 / max(work_elapsed, 1e-06)
                if lag_observe is not None:
                    show_hint = lag_observe(work_fps, target_fps)
                budget = frame_budget if started or hits else max(frame_budget, IDLE_FRAME_SEC)
                leftover = budget - work_elapsed
                if leftover > 0:
                    time.sleep(leftover)
                cycle = time.perf_counter() - t0
                if cycle > 1e-06:
                    inst = 1.0 / cycle
                    fps_ema = inst if fps_ema <= 0 else 0.85 * fps_ema + 0.15 * inst
                if queue_overlay is not None:
                    queue_overlay(rect, mid_x, green_top, green_bot, white_y, fps_ema, show_hint)
                err_since = 0.0
            except Exception as exc:
                click.release()
                set_status(f"Minigame error: {exc}")
                now = time.perf_counter()
                if err_since <= 0.0:
                    err_since = now
                elif now - err_since > ERROR_GIVE_UP_SEC:
                    set_status("Scan keeps failing, restarting the cast.")
                    _reset_rod_after_fail(cfg, should_abort, set_status, "Scan failed")
                    return False
                time.sleep(max(0.05, poll))

    click.release()
    return False


def run_one_cycle(
    cfg: dict[str, Any],
    scanner: Detector,
    tracker: TrackController,
    click: LeftClickController,
    should_abort: AbortFn,
    set_status: StatusFn,
    *,
    queue_overlay: OverlayFn | None = None,
    lag_observe: Callable[[float, float], bool] | None = None,
    on_catch: Callable[[], None] | None = None,
    t_visible: Callable[[], bool | None] | None = None,
) -> bool:
    if not _focus(should_abort, set_status):
        return False

    if not run_cast(cfg=cfg, should_abort=should_abort, set_status=set_status):
        return False

    ok = run_minigame(
        cfg=cfg,
        scanner=scanner,
        tracker=tracker,
        click=click,
        should_abort=should_abort,
        set_status=set_status,
        queue_overlay=queue_overlay,
        lag_observe=lag_observe,
    )
    if not ok or should_abort():
        return False
    if on_catch is not None:
        on_catch()

    set_status("Minigame ended, waiting before collect...")
    if sleep_interruptible(_timing(cfg, "after_minigame_sec"), should_abort):
        return False
    if cfg.get("drop_fish"):
        reset_rod(cfg, should_abort, set_status, why="Dropping fish")
        if should_abort():
            return False
    if not run_collect(cfg, should_abort, set_status, t_visible):
        return False
    if cfg.get("worm_bait"):
        reset_rod(cfg, should_abort, set_status, why="Worm Bait")
        if should_abort():
            return False
    return run_move(cfg, should_abort, set_status)
