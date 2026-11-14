from __future__ import annotations

import json
from typing import Any

from fishing_cycle import MOVE_KEYS, AbortFn, StatusFn, _focus, _pt, _timing
from input_actions import gui_click_point, hold_keys, sleep_interruptible, tap_key
from win_focus import focus_roblox

QUEST_POINT_KEYS = ("quest_dialogue", "quest_lvl60", "quest_accept", "quest_complete", "quest_exit")
QUEST_LEVELS = (45, 60, 105)
QUEST_SIDES = ("out", "back")
QUEST_NUMBERS = ("click_delay_sec", "step_delay_sec", "hold_t_sec", "quest_delay_sec")

DEFAULT_QUEST: dict[str, Any] = {
    "level": 45,
    "clicks": {k: 6 if k == "quest_dialogue" else 1 for k in QUEST_POINT_KEYS},
    "click_delay_sec": 0.5,
    "step_delay_sec": 0.5,
    "hold_t_sec": 3.0,
    "quest_delay_sec": 40.0,
    "out": {k: {"on": False, "sec": 1.0} for k in MOVE_KEYS},
    "back": {k: {"on": False, "sec": 1.0} for k in MOVE_KEYS},
}


def merge_quest(raw: Any) -> dict[str, Any]:
    out = json.loads(json.dumps(DEFAULT_QUEST))
    if not isinstance(raw, dict):
        return out
    clicks = raw.get("clicks") if isinstance(raw.get("clicks"), dict) else {}
    if "quest_dialogue" not in clicks and "dialogue_clicks" in raw:
        clicks = dict(clicks, quest_dialogue=raw["dialogue_clicks"])
    for k in QUEST_POINT_KEYS:
        try:
            out["clicks"][k] = min(50, max(0, int(float(clicks.get(k, out["clicks"][k])))))
        except (TypeError, ValueError):
            pass
    try:
        level = int(float(raw.get("level", out["level"])))
    except (TypeError, ValueError):
        level = out["level"]
    if level in QUEST_LEVELS:
        out["level"] = level
    for key in QUEST_NUMBERS:
        try:
            out[key] = max(0.0, float(raw.get(key, out[key])))
        except (TypeError, ValueError):
            pass
    for side in QUEST_SIDES:
        src = raw.get(side)
        if not isinstance(src, dict):
            continue
        for k in MOVE_KEYS:
            v = src.get(k)
            if not isinstance(v, dict):
                continue
            out[side][k]["on"] = bool(v.get("on"))
            try:
                out[side][k]["sec"] = max(0.0, float(v.get("sec", out[side][k]["sec"])))
            except (TypeError, ValueError):
                pass
    return out


def merge_quest_levels(raw: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for lvl in QUEST_LEVELS:
        src = raw.get(str(lvl))
        if not isinstance(src, dict):
            continue
        entry = merge_quest(src)
        entry["level"] = lvl
        pts = src.get("points") if isinstance(src.get("points"), dict) else {}
        entry["points"] = {}
        for k in QUEST_POINT_KEYS:
            p = pts.get(k)
            try:
                entry["points"][k] = {"x": float(p["x"]), "y": float(p["y"])}
            except (KeyError, TypeError, ValueError):
                pass
        out[str(lvl)] = entry
    return out


def quest_points_needed(cfg: dict) -> tuple[str, ...]:
    q = merge_quest(cfg.get("quest"))
    return tuple(
        k for k in QUEST_POINT_KEYS
        if q["clicks"][k] > 0 and (k != "quest_lvl60" or q["level"] == 60)
    )


def quest_points_set(cfg: dict) -> bool:
    pts = cfg.get("points") or {}
    return all("x" in (pts.get(k) or {}) and "y" in (pts.get(k) or {}) for k in quest_points_needed(cfg))


def _moves(q: dict, side: str) -> dict[str, float]:
    return {k: v["sec"] for k, v in q[side].items() if v["on"] and v["sec"] > 0}


def run_quest_cycle(cfg: dict[str, Any], should_abort: AbortFn, set_status: StatusFn) -> bool:
    q = merge_quest(cfg.get("quest"))
    step_s = q["step_delay_sec"]

    def wait(seconds: float) -> bool:
        return not sleep_interruptible(seconds, should_abort)

    def talk() -> bool:
        set_status("Quest: talking (T)...")
        focus_roblox()
        if tap_key("t", hold_s=_timing(cfg, "key_hold_sec"), should_abort=should_abort):
            return False
        return wait(step_s)

    def click(key: str, text: str) -> bool:
        n = q["clicks"][key]
        for i in range(n):
            set_status(f"Quest: {text} {i + 1}/{n}...")
            if gui_click_point(_pt(cfg, key), settle_s=q["click_delay_sec"], should_abort=should_abort):
                return False
        return not should_abort()

    def dialogue() -> bool:
        return click("quest_dialogue", "clicking dialogue")

    def move(side: str, text: str) -> bool:
        keys = _moves(q, side)
        if not keys:
            return True
        set_status(f"Quest: {text} ({'+'.join(k.upper() for k in keys)})...")
        focus_roblox()
        if hold_keys(keys, should_abort=should_abort):
            return False
        return wait(step_s)

    def hold_t() -> bool:
        if q["hold_t_sec"] <= 0:
            return True
        set_status(f"Quest: holding T {q['hold_t_sec']:.1f}s...")
        focus_roblox()
        if tap_key("t", hold_s=q["hold_t_sec"], should_abort=should_abort):
            return False
        return wait(step_s)

    if not _focus(should_abort, set_status):
        return False
    lvl60 = q["level"] == 60
    return (
        talk()
        and dialogue()
        and (not lvl60 or (click("quest_lvl60", "picking the Lvl 60 quest") and dialogue()))
        and click("quest_accept", "accepting the quest")
        and wait(step_s)
        and move("out", "moving out")
        and hold_t()
        and move("back", "moving back")
        and talk()
        and dialogue()
        and click("quest_complete", "completing the quest")
        and click("quest_exit", "closing the dialogue")
        and wait(step_s)
    )
