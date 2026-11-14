from __future__ import annotations

import difflib
import json
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from dataclasses import asdict
from tkinter import colorchooser, messagebox, ttk


from app_paths import resource_dir, writable_dir
from advanced_settings import ADVANCED_SECTIONS, DEFAULT_ADVANCED, merge_advanced
from area_selector import DEFAULT_SCAN_AREA, AreaSelector, PixelRect
from bar_calibrate import RECORD_SEC, BarDrawer, RecordBanner, crops_from_shots, measure, record
from credits import (
    LABEL_BY_AUTHOR,
    LABEL_YT_HOST,
    YOUTUBE_URL,
)
from free_mouse import FreeMouse
from fishing_cycle import (
    MOVE_KEYS,
    merge_move,
    POINT_KEYS,
    cast_point_set,
    run_one_cycle,
    scan_area_from_cfg,
    scan_rect_screen,
)
from input_actions import release_inputs, sleep_interruptible
from quest_cycle import (
    DEFAULT_QUEST,
    QUEST_LEVELS,
    QUEST_POINT_KEYS,
    QUEST_SIDES,
    merge_quest,
    merge_quest_levels,
    quest_points_set,
    run_quest_cycle,
)
from mouse_control import LeftClickController, apply_mouse_timings
from overlays import (
    FpsOverlay,
    GreenYMarkers,
    LagDetector,
    PerfHintOverlay,
    WhiteYMarker,
    ZoneXMarker,
)
import platform_keys
from point_selector import ClickCapture, FracPoint
from roblox_geo import (
    clamp_rect,
    ensure_dpi_awareness,
    rect_from_screen,
    rect_to_screen,
    resolve_origin,
    virtual_screen_rect,
)
from scan_outline import ScanOutline
from detect import Detector
from track_control import TrackController
from webhook import LiveMessage, Webhook, capture_roblox, embed
from name_reader import NameReader
from win_focus import focus_roblox, minimize_tk, pin_topmost_no_activate, restore_tk

APP_DIR = writable_dir()
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
CONFIG_PATH = APP_DIR / "config.json"
ICON_PATH = resource_dir() / "app.ico"

BG = "#243b55"
SURFACE = "#2f4a68"
FIELD = "#1c2f45"
INK = "#e8eef6"
MUTED = "#a9b8cc"
LINE = "#4a6585"
ACCENT = "#5b8fd6"
ACCENT_DIM = "#3f6ca8"
ACCENT_TX = "#9cc4f5"
LINK = "#9cc4f5"
KEY_FG = "#ffd27a"

HOTKEY_LABELS = {
    "hotkey_1": "Start / Stop",
    "hotkey_2": "Adjust scan area",
    "hotkey_3": "Fishing Bar Color Detect",
    "hotkey_4": "Exit",
}

POINT_LABELS = {
    "cast": "Cast click",
    "collect": "Collect hold",
    "quest_dialogue": "Dialogue box",
    "quest_lvl60": "Lvl 60 Quest",
    "quest_accept": "Accept Quest",
    "quest_complete": "Quest Complete",
    "quest_exit": "Exit Dialogue",
}

DEFAULT_POINTS = {
    "collect": {"x": 0.51015625, "y": 0.4027777777777778},
}

DEFAULT_CONFIG = {
    "hotkeys": {
        "hotkey_1": "F1",
        "hotkey_2": "F2",
        "hotkey_3": "F3",
        "hotkey_4": "F4",
    },
    "scan_area": asdict(DEFAULT_SCAN_AREA),
    "bar_colors": None,
    "welcome_done": False,
    "show_scan_outline": True,
    "show_overlay_arrows": False,
    "show_fps_overlay": False,
    "auto_minimize": False,
    "auto_focus_roblox": True,
    "always_on_top": True,
    "collect_hold_t": True,
    "drop_fish": False,
    "worm_bait": False,
    "webhook_enabled": False,
    "webhook_url": "",
    "webhook_fail": False,
    "webhook_dc": True,
    "webhook_user": "",
    "name_read": True,
    "name_area": None,
    "t_visual": False,
    "t_ignore": [],
    "t_area": None,
    "fish_colors": [],
    "move_enabled": False,
    "move": {k: {"on": k == "w", "sec": 0.5} for k in MOVE_KEYS},
    "mode": "main",
    "quest": DEFAULT_QUEST,
    "quest_levels": {},
    "free_mouse": False,
    "rod_key": "",
    "points": dict(DEFAULT_POINTS),
    "config_rev": 9,
    "advanced": dict(DEFAULT_ADVANCED),
}

CYCLE_ERROR_PAUSE_SEC = 1.5
LISTEN_TIMEOUT_MS = 5000
SHARED_NUMBERS = ("after_minigame_sec", "collect_hold_sec", "after_collect_sec")
NUMBER_MIN = {"collect_hold_sec": 0.05}

WELCOME_ASK = "Would you like to learn how to use this macro?"

WELCOME_GUIDE = "Ok, watch the Project Slayers 2 Ultimate Fishing Macro FULL SETUP GUIDE here:"

GUIDE_URL = "https://www.youtube.com/watch?v=medoNFtBf0s"

QUEST_WARNING = 'Make sure to be careful when macroing the fishing quest, you might get false flagged as a cheater for doing quests too fast, set the delay higher than the default.'

NOTES_TOP = "I'm still learning how to code, I'll update the detection once I learn how to implement it better."

NOTES_TEXT = 'I will consistently update this, I take like 15-20 minutes a day updating this whenever I feel like it'

HELP_TOPICS = (
    ('collect', '1. Collect Fish', (
        "First things first, open the in game menu and disable screenshake and turn on shift lock, otherwise your camera moves around every time you collect and it messes everything up\n\n"
        "Delay is how long it waits after the minigame ends before it collects, Hold is how long it holds the collect and After is how long it waits after collecting before it casts again, the delays determine.. the delays, I don't know how else to put it lol\n\n"
        "Delay (default 2); the fish needs a sec to get reeled in after the minigame ends, if it starts collecting before the T Collect prompt even shows up raise this\n\n"
        "Hold (default 3); how long it holds T (or click) to collect, if the fish keeps getting away halfway through the collect raise this, or just use Visual T collect\n\n"
        "After (default 0.35); the little wait after collecting before it does anything else, raise it if it casts again too early and the cast gets eaten\n\n"
        "Hold T instead; Holds T instead of holding click at your mouse point, I suggest keeping this on, if you turn it off click Select point and click where your collect is\n\n"
        "Drop Fish; this was added since people kept getting diffed by a kraken, this is for people fishing in spots with free space under their rod, it drops the fish in front of you for a smooth collect, it takes your rod off and puts it back on right after Delay and before it collects"
    )),
    ('cast', '2. Cast', (
        "You must equip your fishing rod first, but don't worry if you forget this step since there's a failsafe to equip your rod again\n\n"
        "Type in your rod key to your \"Rod key\" rod key if that makes sense..( ͡° ͜ʖ ͡°) whenever a cast fails it presses your rod key once to equip it again, leave it blank if you don't want that\n\n"
        "Click Select cast point and click on the water where you want it to cast\n\n"
        "Fish manually just once, wait until the fishing minigame pops up and press F2, drag the edges of the box to resize it and overlay it over the in game minigame bar, then press Enter to save it\n\n"
        "Boxes; every box in the macro (scan area, T area, name area, ignore boxes) is just a gray box, whatever is inside the gray is what it uses, drag the middle to move it, drag the edges or corners to resize it, Enter saves and Esc cancels\n\n"
        "Fail cast; if the minigame doesn't show up within 20 seconds of casting it counts as a failed cast, presses your rod key and casts again, you can change the 20 in Advanced (Fail cast timeout)\n\n"
        "Worm Bait; Enable this if you're planning to use worm bait, it takes your rod off and puts it back on after every catch, new fisher huh? ( ͡° ͜ʖ ͡°)\n\n"
        "Click into Roblox and press F1 (or your customized start key) to start fishing, press it again to stop"
    )),
    ('move', '3. Movement', (
        "Tick Hold keys after each catch, each key you tick is held by x duration after you collect, making you go that direction after you successfully pull in the fish and collect it (you can choose the duration yourself), all the ticked keys get held at the same time\n\n"
        "The box next to each key is how many seconds it holds that key, tiny numbers are fine since you only want a little nudge, it happens after the collect (and after Worm Bait if that's on)\n\n"
        "When you equip or unequip your rod your character tends to get thrown around by velocity, so set the direction so it pushes you back and acts like a \"character lock\"\n\n"
        "It's physics based, if you're fishing with bait you'll get flung around quite a lot\n\n"
        "Free mouse (shift lock); This is a windows only option for now, keep it enabled if you want to macro overnight with no issues, you MUST have shift lock enabled for this to work, it stops your character from moving"
    )),
    ('webhook', '4. Webhook', (
        "Automatically comes disabled, if you're planning to afk overnight this is a decent option to have enabled\n\n"
        "To set it up it's pretty simple, go to discord.com and create a private discord server, go to text channels, click the settings cog next to the text channel, click integrations and then webhooks, new webhook, customize it to your liking or just leave it be, click Copy Webhook URL, and paste it into Webhook section, then click Send test to make sure it works\n\n"
        "Right click your username, copy user ID and paste it in the user ID box so it actually pings you when something goes wrong\n\n"
        "If you don't see this option just go to your discord settings and enable developer mode, this lets you see user ID's with a right click\n\n"
        "Send a screenshot after every catch; turns on the catch messages, if Read the fish name is on you get one Fishing Log message that keeps updating with every fish you caught instead of spamming a new message every time\n\n"
        "Send a screenshot after fishing fails for 60 seconds; pings you with a screenshot if nothing got caught for a whole minute\n\n"
        "Ping me every 180 seconds; pings you with a screenshot saying Possibly disconnected OR griefed every 3 minutes you go without a fish, so you know something's up\n\n"
        "Fish name; catch a fish manually and while its name is on screen click Select name area, drag the box over the name and press Enter, Test read shows you what it reads\n\n"
        "Read after (default 0.1); how long it waits after the catch before it reads the name, raise it if the name isn't on screen yet when it reads\n\n"
        "Color grade; click Add fish, type the name how it shows in game and pick a color, that fish gets that colored square in the Fishing Log, Custom lets you pick literally any color"
    )),
    ('visual', '5. Visual T Collect', (
        "This is for when the fish swings around like crazy and goes in and out of the collect range, instead of just holding T for a set time it reads the collect prompt and holds T while it's there\n\n"
        "Tick Visual T collect, catch a fish manually and while the T Collect prompt is on screen click Select T area, drag the box over the whole prompt (the T, the fish name and Collect) and make it a bit bigger so it still sees it when the fish swings, then press Enter\n\n"
        "Click Test while the prompt is up, it should say Letters visible, if it says No 3+ letters in a row your box is probably in the wrong spot\n\n"
        "It holds T as long as it reads 3 or more letters in a row, when the fish swings out and the letters vanish it lets go, and when the fish comes back it presses T again so the collect starts over\n\n"
        "Ignore boxes; if there's other text inside your T area that isn't the prompt (quest text, names, whatever) press + and drag a box over it, it'll never read anything inside that box, Change moves a box and - deletes it\n\n"
        "If it can't read anything at all it just does a normal hold so you don't lose the fish, you can fine tune everything about it in Advanced under Collect fish (check 9. Advanced for what every Visual T delay does)"
    )),
    ('hotkeys', '6. Hotkeys + Bar Colors', (
        "F1 starts and stops the macro, F2 adjusts the scan area, F3 is Fishing Bar Color Detect and F4 closes the macro, you can change any of them by clicking Change and pressing a new key\n\n"
        "Fishing Bar Color Detect is for when the macro doesn't see your fishing bar properly, fish manually and press F3 while the minigame is up, it records for 8 seconds so keep fishing and let the ball fall out of the zone a few times so it turns yellow, it needs to see the green AND the yellow\n\n"
        "After it records drag a box over the whole fishing bar and press Enter, it tells you how many green and yellow frames it could see, if the normal colors already work it doesn't change anything\n\n"
        "If it misses your bar in too many frames it tries a bunch of other color settings by itself and only saves one if it actually works better than the normal colors\n\n"
        "If it ever makes things worse just click Reset colors and it goes back to default\n\n"
        "Boosts; if F3 still can't get it right you can push the colors yourself in Advanced, Green boost is for the green bar, Yellow boost is for the yellow bar and White boost is for the ball, 1 is normal for green and white, higher means it looks harder but too high and it starts grabbing random stuff"
    )),
    ('quest', '7. Fishing Quest', (
        "Tick Enable Fishing Quest in Options, read the warning and you'll be able to click the Fishing Quest tab\n\n"
        "Make sure to be careful when macroing the fishing quest, you might get false flagged as a cheater for doing quests too fast, set the quest delay higher than the default\n\n"
        "Go to the NPC and open the quest dialogue manually, click Select next to each position and click where that button is in game, the Clicks box is how many times it clicks that button\n\n"
        "Pick which quest you want, Lvl 45 and Lvl 105 just skip the Lvl 60 Quest button\n\n"
        "Each quest keeps its own settings, so picking a quest loads its own positions, clicks, delays and moves, a quest you haven't set up yet starts as a copy of the one you were on\n\n"
        "This is what it does every quest; talks to the NPC (T), clicks the dialogue, clicks Lvl 60 Quest and the dialogue again if you picked Lvl 60, accepts the quest, walks out, holds T at the quest spot, walks back, talks to the NPC again, clicks the dialogue, completes the quest and closes the dialogue\n\n"
        "Click delay (default 0.5); the wait after every single click, raise it if it clicks through the dialogue too fast and misses buttons\n\n"
        "Step delay (default 0.5); the wait between each step, like after talking, after walking and after holding T\n\n"
        "Hold T (default 3); how long it holds T at the quest spot, 0 skips it\n\n"
        "Quest delay (default 40); how long it waits before doing the next quest, keep this high so you don't get false flagged\n\n"
        "Move out is the keys it holds to walk from the NPC to the quest spot, Move back walks you back to the NPC, each ticked key gets held for its own seconds and they all get held at the same time\n\n"
        "Make sure you CLICK back into Roblox after setting up the fishing quest, and when you want to go back to fishing tick Enable Main and click the Main tab"
    )),
    ('options', '8. Options', (
        "Auto minimize; minimizes the macro when you start it so it's out of the way\n\n"
        "Auto focus Roblox; switches you back into Roblox when you start so your keys actually go to the game\n\n"
        "Always on top; keeps the macro window on top of Roblox\n\n"
        "Scan outline; draws a pink box around your scan area while it runs so you can see where it's looking\n\n"
        "Overlay arrows; shows what it's tracking on the bar, it's more lag so leave it off unless something's wrong\n\n"
        "Scan FPS; shows how fast it's scanning\n\n"
        "Enable Fishing Quest; unlocks the Fishing Quest tab (check 7. Fishing Quest)\n\n"
        "Overlays off means less lag, so if your game runs bad turn off Scan outline, Overlay arrows and Scan FPS"
    )),
    ('advanced', '9. Advanced', (
        "Everything in Advanced saves as you type, if you mess something up just click Reset defaults\n\n"
        "This is the order it does everything in so you know where each delay goes; casts (Cast click settle, After cast delay), waits for the minigame (Fail cast timeout, Start confirm), plays the minigame (Minigame max, Ball lost timeout), waits (Delay before collect), drops the fish if Drop Fish is on, collects (Collect hold or Visual T), waits (After collect delay), Worm Bait if it's on, moves if Movement is on, then casts again\n\n"
        "MINIGAME TRACKING\n\n"
        "Target FPS (default 30); how many times a second it checks the bar, lower it if your game lags but I wouldn't go under 20\n\n"
        "Hold acceleration, Release acceleration and Ball ref size; how the ball moves, these were measured from the game so you shouldn't need to touch them\n\n"
        "Latency (default 0.1); how far ahead it guesses where the ball stops, raise it if it overshoots the bar\n\n"
        "Hysteresis (default 6); how far off the middle the ball can be before it switches, higher means calmer clicking\n\n"
        "Aim offset (default 0); aims above the middle if it's negative and below the middle if it's positive\n\n"
        "Zone memory (default 2); if it loses the bar for a sec it keeps using the last spot for this long\n\n"
        "Green boost, Yellow boost and White boost; how hard it looks for the green bar, the yellow bar and the white ball, check 6. Hotkeys + Bar Colors\n\n"
        "Ball lost timeout (default 1.5); once the ball is gone for this long it counts the minigame as over and goes to collect\n\n"
        "Start confirm (default 4); how many frames in a row it has to see the bar before it starts playing, higher means less false starts\n\n"
        "Error poll; how long it waits before trying again if the scan errors out, you'll probably never need this\n\n"
        "CAST AND FAIL CAST\n\n"
        "Cast click settle (default 0.08); tiny pause right after the cast click\n\n"
        "After cast delay (default 0.25); how long it waits after casting before it starts looking for the minigame\n\n"
        "Fail cast timeout (default 20); if the minigame doesn't show up in this long it presses your rod key and casts again\n\n"
        "Minigame max (default 20); if the minigame somehow goes on longer than this it just collects anyway\n\n"
        "KEYS\n\n"
        "Key hold (default 0.1); how long it holds T and the rod key every time it taps them, raise it if Roblox misses presses\n\n"
        "COLLECT FISH\n\n"
        "Delay before collect, Collect hold and After collect delay; the same as Delay, Hold and After on the Main tab (check 1. Collect Fish)\n\n"
        "Visual T read every (default 0.2); how often it reads the T area, lower reacts faster to a spinning fish but it's more work for your PC\n\n"
        "Visual T start wait (default 3); how long it looks for the letters when the collect starts, if it sees nothing it just does a normal hold\n\n"
        "Visual T miss (default 0.5); the letters have to be gone this long before it lets go of T, so one bad read doesn't make it let go\n\n"
        "Visual T hold (default 3) and Visual T release (default 0.1); while the letters are still there it holds T for Visual T hold, lets go for Visual T release and holds again\n\n"
        "Visual T full hold (default 2.5); if the letters vanish after it held at least this long it counts the fish as collected, shorter than this means the fish just swung out\n\n"
        "Visual T swing wait (default 1); after the fish swings out this is how long it waits for it to come back\n\n"
        "Visual T gone (default 1); the letters have to stay gone this long before it counts the fish as collected\n\n"
        "Visual T max (default 15); it gives up after this long even if it still reads letters\n\n"
        "MOUSE CLICK FEEL\n\n"
        "Move nudge mid, Move settle and Click hold; the timing for its mouse moves and clicks (the cast, the collect click and the quest buttons), Roblox sometimes ignores clicks that are too fast so raise these a bit if clicks don't register\n\n"
        "WEBHOOK\n\n"
        "Name read delay; same as Read after on the Webhook tab"
    )),
    ('help', '10. Something Broke?', (
        "Minigame isn't being detected; press F2 and make sure the box is right over the fishing bar, if it still doesn't see it use F3 (check 6. Hotkeys + Bar Colors)\n\n"
        "Lagging or low FPS; turn off Scan outline, Overlay arrows and Scan FPS in Options, overlays off means less lag\n\n"
        "It keeps failing the cast; make sure your rod key is right and your cast point is actually on the water\n\n"
        "Your camera keeps moving; disable screenshake in the in game settings and turn on shift lock with Free mouse\n\n"
        "Fish keeps getting away during collect; turn on Visual T collect, or raise Hold if you don't want to use it\n\n"
        "Clicks don't register; raise Click hold and Move settle in Advanced under Mouse click feel\n\n"
        "The quest misclicks; raise Click delay in the Fishing Quest tab and make sure you CLICK back into Roblox before you start\n\n"
        "If you have no clue what's going on just watch the full setup guide linked up top, it should only take ~5 minutes to learn how to use everything"
    )),
)

WEBHOOK_FAIL_SEC = 60
WEBHOOK_DC_SEC = 180
CAUGHT_COLOR = 0x57F287
LOG_TEXT_MAX = 3800
LETTER_CHAIN = 3
FISH_MARK = "\U0001f41f"
SQUARES = (
    ("\u2b1c", 0xFFFFFF), ("\U0001f7e8", 0xFFD200), ("\U0001f7e5", 0xDD2E44),
    ("\U0001f7e7", 0xF4900C), ("\U0001f7e9", 0x78B159), ("\U0001f7e6", 0x55ACEE),
    ("\U0001f7ea", 0xAA8ED6), ("\U0001f7eb", 0xC1694F), ("\u2b1b", 0x31373D),
)
READ_AREA_DEFAULTS = {
    "name_area": {"x": 0.4, "y": 0.3, "w": 0.2, "h": 0.06},
    "t_area": {"x": 0.42, "y": 0.35, "w": 0.18, "h": 0.1},
}
NAME_MATCH = 0.85
CUSTOM_COLOR = "Custom..."
FISH_COLORS = (
    ("White", 0xFFFFFF), ("Gold", 0xF1C40F), ("Red", 0xED4245), ("Orange", 0xE67E22),
    ("Yellow", 0xFEE75C), ("Green", 0x57F287), ("Blue", 0x3498DB), ("Purple", 0x9B59B6),
    ("Pink", 0xEB459E), ("Cyan", 0x1ABC9C), ("Black", 0x23272A),
)

BLOCKED_KEYS = {
    "Win_L", "Win_R", "Escape", "Caps_Lock", "Shift_L", "Shift_R",
    "Control_L", "Control_R", "Alt_L", "Alt_R", "BackSpace", "Tab",
    "Enter", "Return",
}

def font(size: int = 9, weight: str = "normal") -> tuple:
    return ("Segoe UI", size, weight)


def normalize_key(event: tk.Event) -> str | None:
    keysym = event.keysym
    if not keysym or keysym in BLOCKED_KEYS:
        return None
    if keysym.startswith("F") and keysym[1:].isdigit():
        return keysym.upper()
    if len(keysym) == 1:
        return keysym.upper()
    special = {
        "space": "Space",
        "plus": "Plus",
        "minus": "Minus",
        "equal": "Equal",
        "comma": "Comma",
        "period": "Period",
        "slash": "Slash",
        "backslash": "Backslash",
        "bracketleft": "LeftBracket",
        "bracketright": "RightBracket",
        "semicolon": "Semicolon",
        "apostrophe": "Quote",
        "grave": "Grave",
        "Prior": "PageUp",
        "Next": "PageDown",
        "Up": "Up",
        "Down": "Down",
        "Left": "Left",
        "Right": "Right",
        "Insert": "Insert",
        "Delete": "Delete",
        "Home": "Home",
        "End": "End",
    }
    if keysym in special:
        return special[keysym]
    if keysym.lower() in special:
        return special[keysym.lower()]
    return keysym


def _free_key(taken: set, prefer: str) -> str:
    for key in (prefer, "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10"):
        if key.upper() not in taken:
            return key
    return prefer


def _fish_key(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _same_fish(a: str, b: str) -> bool:
    ka, kb = _fish_key(a), _fish_key(b)
    if not ka or not kb:
        return False
    return ka == kb or difflib.SequenceMatcher(None, ka, kb).ratio() >= NAME_MATCH


def _color_value(color: str) -> int | None:
    for name, value in FISH_COLORS:
        if str(color).lower() == name.lower():
            return value
    s = str(color).strip().lstrip("#")
    if len(s) == 6:
        try:
            return int(s, 16)
        except ValueError:
            return None
    return None


def _square(value: int) -> str:
    r, g, b = value >> 16 & 255, value >> 8 & 255, value & 255
    return min(SQUARES, key=lambda s: (r - (s[1] >> 16 & 255)) ** 2 + (g - (s[1] >> 8 & 255)) ** 2 + (b - (s[1] & 255)) ** 2)[0]


def _letter_chain(text: str) -> int:
    best = run = 0
    for ch in str(text):
        run = run + 1 if ch.isalpha() else 0
        best = max(best, run)
    return best


def _area(raw) -> dict | None:
    if not isinstance(raw, dict) or not all(k in raw for k in ("x", "y", "w", "h")):
        return None
    try:
        return {k: float(raw[k]) for k in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None


def _digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:20]


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        bak = CONFIG_PATH.with_suffix(".json.bak")
        try:
            CONFIG_PATH.replace(bak)
        except OSError:
            pass
        save_config(DEFAULT_CONFIG)
        data = {}
        print(f"config.json was invalid ({exc}); reset to defaults (backup: {bak.name})")

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not isinstance(data, dict):
        return cfg
    cfg["hotkeys"].update(data.get("hotkeys", {}))
    if isinstance(data.get("scan_area"), dict):
        cfg["scan_area"].update(data["scan_area"])
    for key in (
        "show_scan_outline",
        "show_overlay_arrows",
        "show_fps_overlay",
        "collect_hold_t",
        "drop_fish",
        "worm_bait",
        "webhook_enabled",
        "webhook_fail",
        "webhook_dc",
        "name_read",
        "t_visual",
        "move_enabled",
        "free_mouse",
        "auto_minimize",
        "auto_focus_roblox",
        "always_on_top",
        "welcome_done",
    ):
        if key in data:
            cfg[key] = bool(data[key])
    colors = data.get("bar_colors")
    if isinstance(colors, dict):
        try:
            cfg["bar_colors"] = {str(k): float(v) for k, v in colors.items()}
        except (TypeError, ValueError):
            pass
    cfg["rod_key"] = str(data.get("rod_key") or "").strip()
    cfg["webhook_url"] = str(data.get("webhook_url") or "").strip()
    cfg["webhook_user"] = _digits(data.get("webhook_user"))
    for key in ("name_area", "t_area"):
        area = _area(data.get(key))
        if area is not None:
            cfg[key] = area
    ignore = data.get("t_ignore")
    if isinstance(ignore, list):
        cfg["t_ignore"] = [a for a in (_area(b) for b in ignore) if a is not None]
    grades = data.get("fish_colors")
    if isinstance(grades, list):
        cfg["fish_colors"] = [
            {"name": str(g.get("name") or "").strip()[:40], "color": str(g.get("color") or "White")}
            for g in grades
            if isinstance(g, dict) and str(g.get("name") or "").strip()
        ]
    if data.get("mode") in ("main", "quest"):
        cfg["mode"] = data["mode"]
    cfg["quest"] = merge_quest(data.get("quest"))
    cfg["quest_levels"] = merge_quest_levels(data.get("quest_levels"))
    cfg["move"] = merge_move(data.get("move"), data.get("move_key"), data.get("move_hold_sec", 0.5))
    if isinstance(data.get("points"), dict):
        for k in POINT_KEYS + QUEST_POINT_KEYS:
            raw = data["points"].get(k)
            if isinstance(raw, dict) and "x" in raw and "y" in raw:
                cfg["points"][k] = {"x": float(raw["x"]), "y": float(raw["y"])}

    cfg["advanced"] = merge_advanced(data.get("advanced"))
    try:
        rev = int(data.get("config_rev", 1))
    except (TypeError, ValueError):
        rev = 1
    if rev < 2:
        cfg["show_overlay_arrows"] = False
        cfg["show_fps_overlay"] = False
        cfg["collect_hold_t"] = True
    if rev < 6 and cfg["quest"]["quest_delay_sec"] == 10.0:
        cfg["quest"]["quest_delay_sec"] = 40.0
    if rev < 8:
        hk = cfg["hotkeys"]
        old_exit = str((data.get("hotkeys") or {}).get("hotkey_3") or "F3")
        taken = {str(hk[k]).upper() for k in ("hotkey_1", "hotkey_2")}
        hk["hotkey_4"] = _free_key(taken, "F4" if old_exit.upper() == "F3" else old_exit)
        taken.add(hk["hotkey_4"].upper())
        hk["hotkey_3"] = _free_key(taken, "F3")
        if cfg["advanced"]["wait_minigame_end_sec"] == 120.0:
            cfg["advanced"]["wait_minigame_end_sec"] = 20.0
        if cfg["advanced"]["zone_hold_s"] == 1.0:
            cfg["advanced"]["zone_hold_s"] = 2.0
    if rev < 9 and cfg["advanced"]["yellow_boost"] == 0.5:
        cfg["advanced"]["yellow_boost"] = 0.8
    return cfg


def save_config(cfg: dict) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("1vtt's Project Slayers 2 Fishing Macro")
        self.minsize(400, 560)
        self.geometry("420x660")
        self.configure(bg=BG)
        self._images: dict[str, tk.PhotoImage] = {}
        for name in ("app.png", "fish.png"):
            try:
                self._images[name] = tk.PhotoImage(file=str(resource_dir() / name))
            except tk.TclError:
                pass
        try:
            if sys.platform == "win32" and ICON_PATH.is_file():
                self.iconbitmap(default=str(ICON_PATH))
            elif "app.png" in self._images:
                self.iconphoto(True, self._images["app.png"])
        except tk.TclError:
            pass

        self.cfg = load_config()
        self._listening_for: str | None = None
        self._listen_timer: str | None = None
        self._hotkey_btns: dict[str, ttk.Button] = {}
        self._hotkey_vars: dict[str, tk.StringVar] = {}
        self._hotkey_handles: list = []
        self._status = tk.StringVar(value="Ready. F1 runs, F2 adjusts the scan area.")
        self._running = False
        self._closing = False
        self._area_selector: AreaSelector | None = None
        self._click_capture: ClickCapture | None = None
        self._bar_drawer: BarDrawer | None = None
        self._bar_colors_label = tk.StringVar()
        self._bar_record_stop: threading.Event | None = None
        self._record_banner = RecordBanner(self)

        self.show_scan_outline = tk.BooleanVar(value=self.cfg["show_scan_outline"])
        self.show_overlay_arrows = tk.BooleanVar(value=self.cfg["show_overlay_arrows"] and not IS_MAC)
        self.show_fps_overlay = tk.BooleanVar(value=self.cfg["show_fps_overlay"] and not IS_MAC)
        self.auto_minimize = tk.BooleanVar(value=self.cfg["auto_minimize"])
        self.auto_focus_roblox = tk.BooleanVar(value=self.cfg["auto_focus_roblox"])
        self.always_on_top = tk.BooleanVar(value=self.cfg["always_on_top"])
        self.collect_hold_t = tk.BooleanVar(value=self.cfg["collect_hold_t"])
        self.drop_fish = tk.BooleanVar(value=self.cfg["drop_fish"])
        self.worm_bait = tk.BooleanVar(value=self.cfg["worm_bait"])
        self.webhook_enabled = tk.BooleanVar(value=self.cfg["webhook_enabled"])
        self.webhook_url = tk.StringVar(value=self.cfg["webhook_url"])
        self.webhook_fail = tk.BooleanVar(value=self.cfg["webhook_fail"])
        self.webhook_dc = tk.BooleanVar(value=self.cfg["webhook_dc"])
        self.webhook_user = tk.StringVar(value=self.cfg["webhook_user"])
        self.name_read = tk.BooleanVar(value=self.cfg["name_read"])
        self._name_area_label = tk.StringVar()
        self.t_visual = tk.BooleanVar(value=self.cfg["t_visual"])
        self._t_area_label = tk.StringVar()
        self._help_topic = tk.StringVar(value=HELP_TOPICS[0][0])
        self.free_mouse = tk.BooleanVar(value=self.cfg["free_mouse"] and IS_WINDOWS)
        self.move_enabled = tk.BooleanVar(value=self.cfg["move_enabled"])
        move_cfg = merge_move(self.cfg.get("move"))
        self._move = {
            k: (tk.BooleanVar(value=move_cfg[k]["on"]), tk.StringVar(value=str(move_cfg[k]["sec"])))
            for k in MOVE_KEYS
        }
        self.enable_main = tk.BooleanVar(value=False)
        self.enable_quest = tk.BooleanVar(value=False)
        quest = merge_quest(self.cfg.get("quest"))
        self._quest_vars = {
            k: tk.StringVar(value=str(quest[k]))
            for k in ("click_delay_sec", "step_delay_sec", "hold_t_sec", "quest_delay_sec")
        }
        self._quest_clicks = {k: tk.StringVar(value=str(quest["clicks"][k])) for k in QUEST_POINT_KEYS}
        self._quest_move = {
            (side, k): (tk.BooleanVar(value=quest[side][k]["on"]), tk.StringVar(value=str(quest[side][k]["sec"])))
            for side in QUEST_SIDES
            for k in MOVE_KEYS
        }
        self._quest_point_labels = {k: tk.StringVar() for k in QUEST_POINT_KEYS}
        self._quest_point_btns: dict[str, ttk.Button] = {}
        self.quest_level = tk.StringVar(value=str(quest["level"]))
        self.rod_key = tk.StringVar(value=self.cfg["rod_key"])
        self._advanced_vars = {key: tk.StringVar(value=str(self.cfg["advanced"][key])) for key in DEFAULT_ADVANCED}
        for var in self._advanced_vars.values():
            var.trace_add("write", lambda *_: self._persist())
        self._cast_point_label = tk.StringVar()
        self._collect_point_label = tk.StringVar()

        self._scanner = Detector()
        self._scan_outline = ScanOutline(self)
        self._zone_marker = ZoneXMarker(self)
        self._green_markers = GreenYMarkers(self)
        self._white_marker = WhiteYMarker(self)
        self._fps_overlay = FpsOverlay(self)
        self._perf_hint = PerfHintOverlay(self)
        self._lag_detector = LagDetector()
        self._click = LeftClickController()
        self._tracker = TrackController()
        self._webhook = Webhook()
        self._name_reader = NameReader()
        self._catches = 0
        self._run_started = 0.0
        self._last_catch = 0.0
        self._fail_sent = False
        self._dc_sent = 0
        self._live_log = LiveMessage()
        self._tally: dict[str, int] = {}
        self._escaped = 0
        self._tally_lock = threading.Lock()
        self._grade_rows: list[dict] = []
        self._free_mouse = FreeMouse()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._overlay_pending = None
        self._overlay_scheduled = False
        self._persisting = False
        self._posted: queue.SimpleQueue = queue.SimpleQueue()
        self.after(15, self._pump_posted)
        self._apply_runtime_settings()

        self._build_ui()
        self._refresh_point_summaries()
        self._apply_always_on_top()
        self._register_hotkeys()
        self._apply_free_mouse()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<KeyPress>", self._on_key_press)
        self.bind_all("<ButtonPress-1>", self._on_any_click, add="+")
        if IS_MAC:
            self.after(300, self._startup_checks)
        elif not self.cfg.get("welcome_done"):
            self.after(400, self._welcome)

    def _startup_checks(self) -> None:
        self._check_mac_permissions()
        if not self.cfg.get("welcome_done"):
            self._welcome()

    def _check_mac_permissions(self) -> None:
        where = "System Settings > Privacy & Security"
        missing = []
        try:
            import Quartz
            if not Quartz.CGPreflightScreenCaptureAccess():
                Quartz.CGRequestScreenCaptureAccess()
                missing.append("Screen Recording")
            if not Quartz.CGPreflightListenEventAccess():
                Quartz.CGRequestListenEventAccess()
                missing.append("Input Monitoring")
        except Exception:
            pass
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
            if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
                missing.append("Accessibility")
        except Exception:
            pass
        if missing:
            self._status.set("Allow %s for Terminal under %s, then start this again." % (" + ".join(missing), where))

    def _style(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=INK, fieldbackground=FIELD, font=font(9))
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=INK)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Key.TLabel", background=FIELD, foreground=KEY_FG, font=font(9, "bold"), anchor="center", padding=(6, 2))
        s.configure("TLabelframe", background=BG, bordercolor=LINE, relief="groove")
        s.configure("TLabelframe.Label", background=BG, foreground=ACCENT_TX, font=font(9, "bold"))
        s.configure("TCheckbutton", background=BG, foreground=INK)
        s.map("TCheckbutton", background=[("active", BG)], indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])
        s.configure("TRadiobutton", background=BG, foreground=INK)
        s.map("TRadiobutton", background=[("active", BG)], indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])
        s.configure("TButton", background=SURFACE, foreground=INK, bordercolor=LINE, padding=(8, 2))
        s.map("TButton", background=[("active", ACCENT), ("pressed", ACCENT_DIM)])
        s.configure("Big.TButton", font=font(14, "bold"), padding=(10, 8))
        s.configure("Toolbutton", background=SURFACE, foreground=INK, bordercolor=LINE, padding=(8, 4), anchor="center")
        s.map("Toolbutton", background=[("selected", ACCENT_DIM), ("active", ACCENT)])
        s.configure("TEntry", fieldbackground=FIELD, foreground=INK, insertcolor=INK, bordercolor=LINE)
        s.configure("TSpinbox", fieldbackground=FIELD, foreground=INK, insertcolor=INK, bordercolor=LINE, arrowcolor=INK, background=SURFACE)
        s.configure("TCombobox", fieldbackground=FIELD, foreground=INK, bordercolor=LINE, arrowcolor=INK, background=SURFACE)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", INK)], selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", INK)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", INK)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DIM)
        s.configure("TNotebook", background=BG, bordercolor=LINE, tabmargins=(2, 4, 2, 0))
        s.configure("TNotebook.Tab", background=SURFACE, foreground=INK, padding=(6, 3))
        s.map("TNotebook.Tab", background=[("selected", ACCENT_DIM)], foreground=[("disabled", MUTED), ("selected", INK)])
        s.configure("Vertical.TScrollbar", background=SURFACE, troughcolor=BG, bordercolor=LINE, arrowcolor=INK)

    def _link_label(self, parent, text: str, url: str) -> ttk.Label:
        lbl = ttk.Label(parent, text=text, foreground=LINK, cursor="hand2")
        lbl.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
        return lbl

    def _entry(self, parent, var, width=8):
        return ttk.Entry(parent, textvariable=var, width=width)

    def _number_entry(self, parent, key: str, width: int) -> ttk.Entry:
        var = self._advanced_vars[key]
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.bind("<FocusOut>", lambda _e, k=key: self._tidy_number(k))
        return entry

    def _tidy_number(self, key: str) -> None:
        var = self._advanced_vars[key]
        try:
            float(var.get())
        except ValueError:
            var.set(str(self.cfg["advanced"][key]))

    def _build_ui(self) -> None:
        self._style()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(8, 8, 8, 4))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self._start_btn = ttk.Button(top, text="Press To Start (F1)", style="Big.TButton", command=self._on_hotkey_start_stop)
        self._start_btn.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(top, text=LABEL_BY_AUTHOR, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._link_label(top, LABEL_YT_HOST, YOUTUBE_URL).grid(row=1, column=1, sticky="e", pady=(4, 0))

        self._tabs = ttk.Notebook(self)
        self._tabs.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        main_tab = ttk.Frame(self._tabs)
        help_tab = ttk.Frame(self._tabs)
        adv_tab = ttk.Frame(self._tabs)
        quest_tab = ttk.Frame(self._tabs)
        webhook_tab = ttk.Frame(self._tabs)
        notes_tab = ttk.Frame(self._tabs)
        self._tabs.add(main_tab, text="Main")
        self._tabs.add(help_tab, text="How to Use")
        self._tabs.add(adv_tab, text="Advanced")
        self._tabs.add(quest_tab, text="Fishing Quest")
        self._tabs.add(webhook_tab, text="Webhook")
        self._tabs.add(notes_tab, text="Notes")
        self._main_tab = main_tab
        self._quest_tab = quest_tab
        self._build_main_tab(main_tab)
        self._build_advanced_tab(adv_tab)
        self._build_quest_tab(quest_tab)
        self._build_webhook_tab(webhook_tab)
        self._build_help_tab(help_tab)
        self._build_notes_tab(notes_tab)
        self._apply_mode_tabs()
        self._tabs.select(quest_tab if self._mode() == "quest" else main_tab)
        self._tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        foot = ttk.Frame(self, padding=(8, 2, 8, 6))
        foot.grid(row=2, column=0, sticky="ew")
        if "fish.png" in self._images:
            ttk.Label(foot, image=self._images["fish.png"]).pack(side="left", padx=(0, 6))
        ttk.Label(foot, textvariable=self._status, style="Muted.TLabel", wraplength=350, anchor="w").pack(side="left", fill="x", expand=True)

    def _scrollable(self, parent, row: int) -> ttk.Frame:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(row, weight=1)
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=row, column=0, sticky="nsew", padx=(6, 0), pady=6)
        bar.grid(row=row, column=1, sticky="ns", pady=6)
        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))

        def wheel(e):
            if not canvas.winfo_exists():
                return
            step = -1 if (getattr(e, "num", 0) == 4 or e.delta > 0) else 1
            canvas.yview_scroll(step, "units")

        def grab(_e):
            canvas.bind_all("<MouseWheel>", wheel)
            canvas.bind_all("<Button-4>", wheel)
            canvas.bind_all("<Button-5>", wheel)

        def drop(_e):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", grab)
        canvas.bind("<Leave>", drop)
        return inner

    def _build_main_tab(self, outer) -> None:
        parent = self._scrollable(outer, 0)
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        hk = ttk.LabelFrame(parent, text="Hotkeys", padding=6)
        hk.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        hk.columnconfigure(1, weight=1)
        for r, key_id in enumerate(("hotkey_1", "hotkey_2", "hotkey_3", "hotkey_4")):
            ttk.Label(hk, text=HOTKEY_LABELS[key_id]).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=1)
            var = tk.StringVar(value=self.cfg["hotkeys"][key_id])
            self._hotkey_vars[key_id] = var
            ttk.Label(hk, textvariable=var, style="Key.TLabel", width=8).grid(row=r, column=1, sticky="w", pady=1)
            btn = ttk.Button(hk, text="Change", width=11, command=lambda kid=key_id: self._start_listen(kid))
            btn.grid(row=r, column=2, sticky="e", pady=1)
            self._hotkey_btns[key_id] = btn
        ttk.Label(hk, textvariable=self._bar_colors_label, style="Muted.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(hk, text="Reset colors", width=11, command=self._reset_bar_colors).grid(row=4, column=2, sticky="e", pady=(4, 0))
        ttk.Label(hk, text="Fishing Bar Color Detect: if the macro doesn't see your bar, fish manually and press the hotkey while the minigame is up. Keep fishing while it records for 8 seconds (let the ball slip in and out of the bar so it sees green AND yellow), then click and drag a box over the fishing bar and press Enter.", style="Muted.TLabel", wraplength=360, justify="left").grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 0))
        self._refresh_bar_colors_label()

        col = ttk.LabelFrame(parent, text="1. Collect fish", padding=6)
        col.grid(row=1, column=0, sticky="nsew", padx=(0, 3), pady=(0, 6))
        ttk.Label(col, text="Delay (sec)").grid(row=0, column=0, sticky="w")
        self._number_entry(col, "after_minigame_sec", width=6).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(col, text="Hold (sec)").grid(row=1, column=0, sticky="w")
        self._number_entry(col, "collect_hold_sec", width=6).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(col, text="After (sec)").grid(row=2, column=0, sticky="w")
        self._number_entry(col, "after_collect_sec", width=6).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Checkbutton(col, text="Hold T instead", variable=self.collect_hold_t, command=self._on_collect_mode_toggle).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._collect_select_btn = ttk.Button(col, text="Select point", command=lambda: self._capture_point("collect"))
        self._collect_select_btn.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(col, textvariable=self._collect_point_label, style="Muted.TLabel").grid(row=5, column=0, columnspan=2, sticky="w")
        t_row = col.grid_size()[1]
        ttk.Checkbutton(col, text="Drop Fish", variable=self.drop_fish, command=self._persist).grid(row=t_row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(col, text="Drops your fish after catch, pretty self explanatory", style="Muted.TLabel", wraplength=170, justify="left").grid(row=t_row + 1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(col, text="Visual T collect", variable=self.t_visual, command=self._on_t_visual_toggled).grid(row=t_row + 2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tbtn = ttk.Frame(col)
        tbtn.grid(row=t_row + 3, column=0, columnspan=2, sticky="w", pady=(2, 0))
        ttk.Button(tbtn, text="Select T area", command=lambda: self._select_read_area("t_area")).pack(side="left")
        ttk.Button(tbtn, text="Test", width=5, command=self._test_t_read).pack(side="left", padx=(4, 0))
        ttk.Label(col, textvariable=self._t_area_label, style="Muted.TLabel").grid(row=t_row + 4, column=0, columnspan=2, sticky="w")
        ttk.Label(col, text="Holds T while 3+ letters in a row are read on the collect prompt (Collect, the fish name) and lets go when they're gone. Drag the T area over the whole prompt, a bit bigger for the swing", style="Muted.TLabel", wraplength=170, justify="left").grid(row=t_row + 5, column=0, columnspan=2, sticky="w")
        ttk.Label(col, text="Ignore boxes").grid(row=t_row + 6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._ignore_rows = ttk.Frame(col)
        self._ignore_rows.grid(row=t_row + 7, column=0, columnspan=2, sticky="w")
        ttk.Button(col, text="+", width=3, command=lambda: self._select_ignore(None)).grid(row=t_row + 8, column=0, sticky="w", pady=(2, 0))
        ttk.Label(col, text="Text inside an ignore box is never read. + adds a box, - removes it, Change moves it", style="Muted.TLabel", wraplength=170, justify="left").grid(row=t_row + 9, column=0, columnspan=2, sticky="w")
        self._refresh_ignore_rows()
        self._refresh_t_area_label()

        right = ttk.Frame(parent)
        right.grid(row=1, column=1, sticky="nsew", padx=(3, 0), pady=(0, 6))
        right.columnconfigure(0, weight=1)
        cast = ttk.LabelFrame(right, text="2. Cast", padding=6)
        cast.grid(row=0, column=0, sticky="new")
        notes = ttk.LabelFrame(right, text="Notes", padding=6)
        notes.grid(row=1, column=0, sticky="new", pady=(6, 0))
        ttk.Label(notes, text='If you\'re confused on how to use the macro, check the "How to Use" section, it should only take ~5 minutes to learn how to utilize all the functions', style="Muted.TLabel", wraplength=170, justify="left").grid(row=0, column=0, sticky="w")
        self._cast_select_btn = ttk.Button(cast, text="Select cast point", command=lambda: self._capture_point("cast"))
        self._cast_select_btn.grid(row=1, column=0, sticky="w")
        ttk.Label(cast, textvariable=self._cast_point_label, style="Muted.TLabel").grid(row=2, column=0, sticky="w")
        rrow = ttk.Frame(cast)
        rrow.grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Label(rrow, text="Rod key").pack(side="left")
        self._entry(rrow, self.rod_key, width=4).pack(side="left", padx=(6, 0))
        self.rod_key.trace_add("write", lambda *_: self._persist())
        ttk.Label(cast, text="Fail cast: presses it once to equip it again. Blank = skip.", style="Muted.TLabel", wraplength=170, justify="left").grid(row=4, column=0, sticky="w")
        ttk.Label(cast, text="Disable Screenshake in Settings otherwise your camera will move during each collect, make sure to also enable shiftlock :)", style="Muted.TLabel", wraplength=170, justify="left").grid(row=5, column=0, sticky="w", pady=(6, 0))
        w_row = cast.grid_size()[1]
        ttk.Checkbutton(cast, text="Worm Bait", variable=self.worm_bait, command=self._persist).grid(row=w_row, column=0, sticky="w", pady=(6, 0))
        ttk.Label(cast, text="Enable this if you're planning to use worm bait, new fisher huh? ( ͡° ͜ʖ ͡°)", style="Muted.TLabel", wraplength=170, justify="left").grid(row=w_row + 1, column=0, sticky="w")

        move = ttk.LabelFrame(parent, text="3. Movement", padding=6)
        move.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Checkbutton(move, text="Hold keys after each catch", variable=self.move_enabled, command=self._persist).grid(row=0, column=0, sticky="w")
        mrow = ttk.Frame(move)
        mrow.grid(row=1, column=0, sticky="w", pady=(4, 0))
        for k in MOVE_KEYS:
            on, sec = self._move[k]
            ttk.Checkbutton(mrow, text=k.upper(), variable=on, command=self._persist).pack(side="left")
            self._entry(mrow, sec, width=5).pack(side="left", padx=(2, 10))
            sec.trace_add("write", lambda *_: self._persist())
        ttk.Label(move, text="Ticked keys are held at the same time, each for its own seconds.", style="Muted.TLabel", wraplength=360, justify="left").grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Label(move, text='When equipping/unequipping a rod, your character tends to get thrown around by velocity, adjust the movement direction so that it acts as a "character lock"', style="Muted.TLabel", wraplength=360, justify="left").grid(row=2, column=0, sticky="w")
        free_cb = ttk.Checkbutton(move, text="Free mouse (shift lock)", variable=self.free_mouse, command=self._on_free_mouse_toggled)
        free_cb.grid(row=4, column=0, sticky="w", pady=(8, 0))
        if not IS_WINDOWS:
            free_cb.configure(state="disabled")
        free_text = (
            "Keep this enabled if you want to be able to macro overnight with no issues, "
            "you MUST have shiftlock enabled for this to work, stops your character from moving"
            if IS_WINDOWS
            else "Free mouse is Windows only."
        )
        ttk.Label(move, text=free_text, style="Muted.TLabel", wraplength=360, justify="left").grid(row=5, column=0, sticky="w")

        opts = ttk.LabelFrame(parent, text="Options", padding=6)
        opts.grid(row=3, column=0, columnspan=2, sticky="ew")
        opts.columnconfigure(0, weight=1)
        opts.columnconfigure(1, weight=1)
        items = (
            ("Auto minimize", self.auto_minimize, self._on_auto_minimize_toggled),
            ("Auto focus Roblox", self.auto_focus_roblox, self._persist),
            ("Always on top", self.always_on_top, self._on_always_on_top_toggled),
            ("Scan outline", self.show_scan_outline, self._on_overlay_toggles),
            ("Overlay arrows", self.show_overlay_arrows, self._on_overlay_toggles),
            ("Scan FPS", self.show_fps_overlay, self._on_overlay_toggles),
            ("Enable Fishing Quest", self.enable_quest, self._on_enable_quest),
        )
        for i, (text, var, cmd) in enumerate(items):
            cb = ttk.Checkbutton(opts, text=text, variable=var, command=cmd)
            cb.grid(row=i // 2, column=i % 2, sticky="w", pady=1)
            if IS_MAC and var in (self.show_overlay_arrows, self.show_fps_overlay):
                cb.configure(state="disabled")
        note_row = (len(items) + 1) // 2
        ttk.Label(opts, text="F2 sets the scan area. Overlays off = less lag.", style="Muted.TLabel").grid(row=note_row, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _build_quest_tab(self, outer) -> None:
        parent = self._scrollable(outer, 0)
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Checkbutton(top, text="Enable Main", variable=self.enable_main, command=self._apply_mode_tabs).grid(row=0, column=0, sticky="w")
        ttk.Label(top, text="Tick this and click the Main tab when you want to go back to normal fishing", style="Muted.TLabel", wraplength=360, justify="left").grid(row=1, column=0, sticky="w")

        pos = ttk.LabelFrame(parent, text="1. Positions", padding=6)
        pos.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        pos.columnconfigure(3, weight=1)
        ttk.Label(pos, text="Clicks", style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
        for r, key in enumerate(QUEST_POINT_KEYS, 1):
            ttk.Label(pos, text=POINT_LABELS[key]).grid(row=r, column=0, sticky="w", pady=1)
            btn = ttk.Button(pos, text="Select", command=lambda k=key: self._capture_point(k))
            btn.grid(row=r, column=1, sticky="w", padx=6, pady=1)
            self._quest_point_btns[key] = btn
            clicks = self._quest_clicks[key]
            self._entry(pos, clicks, width=4).grid(row=r, column=2, sticky="w", padx=(0, 6), pady=1)
            clicks.trace_add("write", lambda *_: self._on_quest_level())
            ttk.Label(pos, textvariable=self._quest_point_labels[key], style="Muted.TLabel").grid(row=r, column=3, sticky="w")
        ttk.Label(pos, text="Make sure you CLICK back into Roblox after setting up the fishing quest", style="Muted.TLabel", wraplength=360, justify="left").grid(row=len(QUEST_POINT_KEYS) + 1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        steps = ttk.LabelFrame(parent, text="2. Quest", padding=6)
        steps.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        lrow = ttk.Frame(steps)
        lrow.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(lrow, text="Which quest").pack(side="left", padx=(0, 6))
        for lvl in QUEST_LEVELS:
            ttk.Radiobutton(lrow, text=f"Lvl {lvl}", value=str(lvl), variable=self.quest_level, command=self._on_quest_pick).pack(side="left", padx=(0, 6))
        rows = (
            ("click_delay_sec", "Click delay (sec)"),
            ("step_delay_sec", "Step delay (sec)"),
            ("hold_t_sec", "Hold T (sec)"),
            ("quest_delay_sec", "Quest delay (sec)"),
        )
        for r, (key, label) in enumerate(rows, 1):
            ttk.Label(steps, text=label).grid(row=r, column=0, sticky="w", pady=1)
            var = self._quest_vars[key]
            self._entry(steps, var, width=6).grid(row=r, column=1, sticky="w", padx=6, pady=1)
            var.trace_add("write", lambda *_: self._persist())
        ttk.Label(steps, text="Set the quest delay higher than the default so you don't get false flagged for doing quests too fast", style="Muted.TLabel", wraplength=360, justify="left").grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        for c, (side, title) in enumerate((("out", "3. Move out"), ("back", "4. Move back"))):
            box = ttk.LabelFrame(parent, text=title, padding=6)
            box.grid(row=3, column=c, sticky="nsew", padx=(0, 3) if c == 0 else (3, 0), pady=(0, 6))
            for r, k in enumerate(MOVE_KEYS):
                on, sec = self._quest_move[(side, k)]
                ttk.Checkbutton(box, text=k.upper(), variable=on, command=self._persist).grid(row=r, column=0, sticky="w", pady=1)
                self._entry(box, sec, width=6).grid(row=r, column=1, sticky="w", padx=4, pady=1)
                ttk.Label(box, text="sec", style="Muted.TLabel").grid(row=r, column=2, sticky="w")
                sec.trace_add("write", lambda *_: self._persist())
        ttk.Label(parent, text="Move out is the keys it holds to walk from the NPC to the quest spot, Move back walks you back to the NPC", style="Muted.TLabel", wraplength=360, justify="left").grid(row=4, column=0, columnspan=2, sticky="w")

    def _mode(self) -> str:
        return "quest" if self.cfg.get("mode") == "quest" else "main"

    def _apply_mode_tabs(self) -> None:
        quest = self._mode() == "quest"
        self._tabs.tab(self._main_tab, state="normal" if (not quest or self.enable_main.get()) else "disabled")
        self._tabs.tab(self._quest_tab, state="normal" if (quest or self.enable_quest.get()) else "disabled")

    def _on_enable_quest(self) -> None:
        if not self.enable_quest.get() or self._mode() == "quest":
            self._apply_mode_tabs()
            return
        self._quest_warning()

    def _dialog(self, title: str, message: str):
        win = tk.Toplevel(self)
        win.withdraw()
        win.title(title)
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        fish = self._images.get("fish.png")
        if fish is not None:
            self._images["fish_big.png"] = fish.zoom(3)
            ttk.Label(frame, image=self._images["fish_big.png"]).pack(pady=(0, 8))
        text = ttk.Label(frame, text=message, wraplength=300, justify="center")
        text.pack()
        row = ttk.Frame(frame)
        row.pack(pady=(12, 0))
        return win, frame, text, row

    def _show_dialog(self, win: tk.Toplevel, buttons: list, ready: dict, seconds: int = 3) -> None:
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.deiconify()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.focus_force()

        def tick(left: int) -> None:
            try:
                if left > 0:
                    for button, label in buttons:
                        button.configure(text=f"{label} ({left})")
                    win.after(1000, tick, left - 1)
                    return
                ready["open"] = True
                for button, label in buttons:
                    button.configure(text=label, state="normal")
            except tk.TclError:
                pass

        tick(seconds)

    def _quest_warning(self) -> None:
        win, _frame, _text, row = self._dialog("Fishing Quest", QUEST_WARNING)
        ok = ttk.Button(row, text="OK", state="disabled")
        nah = ttk.Button(row, text="NUH UH", state="disabled")
        ok.pack(side="left", padx=6)
        nah.pack(side="left", padx=6)
        ready = {"open": False}

        def close(accept: bool) -> None:
            if not ready["open"]:
                return
            ready["open"] = False
            try:
                win.grab_release()
            except tk.TclError:
                pass
            win.destroy()
            if accept:
                self._status.set("Fishing Quest unlocked. Click the Fishing Quest tab.")
            else:
                self.enable_quest.set(False)
                self._status.set("Fishing Quest stays off.")
            self._apply_mode_tabs()

        ok.configure(command=lambda: close(True))
        nah.configure(command=lambda: close(False))
        win.protocol("WM_DELETE_WINDOW", lambda: close(False))
        self._show_dialog(win, [(ok, "OK"), (nah, "NUH UH")], ready)

    def _on_tab_changed(self, _event=None) -> None:
        try:
            sel = self._tabs.select()
        except tk.TclError:
            return
        if sel == str(self._quest_tab):
            want = "quest"
        elif sel == str(self._main_tab):
            want = "main"
        else:
            return
        if want == self._mode():
            return
        if self._running:
            self._tabs.select(self._quest_tab if self._mode() == "quest" else self._main_tab)
            self._status.set("Stop first, then switch.")
            return
        self.cfg["mode"] = want
        self.enable_main.set(False)
        self.enable_quest.set(False)
        self._persist()
        self._apply_mode_tabs()
        if want == "quest":
            self._status.set("Fishing Quest is on. F1 runs the quest.")
        else:
            self._status.set("Main is on. F1 runs the fishing macro.")

    def _collect_quest(self) -> dict:
        raw = {k: v.get() for k, v in self._quest_vars.items()}
        raw["level"] = self.quest_level.get()
        raw["clicks"] = {k: v.get() for k, v in self._quest_clicks.items()}
        for side in QUEST_SIDES:
            raw[side] = {
                k: {"on": self._quest_move[(side, k)][0].get(), "sec": self._quest_move[(side, k)][1].get()}
                for k in MOVE_KEYS
            }
        return merge_quest(raw)

    def _refresh_quest_ui(self) -> None:
        no60 = merge_quest(self.cfg.get("quest"))["level"] != 60
        for key, var in self._quest_point_labels.items():
            off = key == "quest_lvl60" and no60
            var.set("Lvl 60 only" if off else self._point_summary(key))
            btn = self._quest_point_btns.get(key)
            if btn is not None:
                btn.configure(state="disabled" if off else "normal")

    def _on_quest_level(self) -> None:
        self._persist()
        self._refresh_quest_ui()

    def _quest_snapshot(self) -> dict:
        q = self._collect_quest()
        pts = self.cfg.get("points") or {}
        q["points"] = {k: dict(pts[k]) for k in QUEST_POINT_KEYS if k in pts}
        return q

    def _on_quest_pick(self) -> None:
        old = str(self.cfg["quest"]["level"])
        new = self.quest_level.get()
        if new == old:
            return
        levels = self.cfg.setdefault("quest_levels", {})
        snap = self._quest_snapshot()
        snap["level"] = int(old)
        levels[old] = snap
        q = levels.get(new) or dict(snap, level=int(new))
        self._persisting = True
        try:
            for k, var in self._quest_vars.items():
                var.set(str(q[k]))
            for k, var in self._quest_clicks.items():
                var.set(str(q["clicks"][k]))
            for (side, k), (on, sec) in self._quest_move.items():
                on.set(q[side][k]["on"])
                sec.set(str(q[side][k]["sec"]))
            pts = self.cfg.setdefault("points", {})
            for k in QUEST_POINT_KEYS:
                if k in q["points"]:
                    pts[k] = dict(q["points"][k])
                else:
                    pts.pop(k, None)
        finally:
            self._persisting = False
        self._persist()
        self._refresh_quest_ui()
        self._status.set(f"Loaded the Lvl {new} quest settings.")

    def _build_webhook_tab(self, outer) -> None:
        parent = self._scrollable(outer, 0)
        parent.columnconfigure(0, weight=1)
        box = ttk.LabelFrame(parent, text="Discord webhook", padding=8)
        box.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        box.columnconfigure(0, weight=1)
        ttk.Checkbutton(box, text="Send a screenshot after every catch", variable=self.webhook_enabled, command=self._persist).grid(row=0, column=0, sticky="w")
        fails = ttk.Frame(box)
        fails.grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Checkbutton(fails, text="Send a screenshot after fishing fails for 60 seconds", variable=self.webhook_fail, command=self._persist).pack(anchor="w")
        ttk.Checkbutton(fails, text='Ping me every 180 seconds with no fish caught ("Possibly disconnected OR griefed")', variable=self.webhook_dc, command=self._persist).pack(anchor="w", pady=(2, 0))
        ttk.Label(box, text="Webhook URL").grid(row=2, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(box, textvariable=self.webhook_url).grid(row=3, column=0, sticky="ew")
        self.webhook_url.trace_add("write", lambda *_: self._persist())
        ttk.Label(box, text="Your Discord user ID (pinged when fishing fails)").grid(row=4, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(box, textvariable=self.webhook_user, width=24).grid(row=5, column=0, sticky="w")
        self.webhook_user.trace_add("write", lambda *_: self._persist())
        ttk.Button(box, text="Send test", command=self._test_webhook).grid(row=6, column=0, sticky="w", pady=(10, 0))
        names = ttk.LabelFrame(parent, text="Fish name", padding=8)
        names.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        names.columnconfigure(1, weight=1)
        ttk.Checkbutton(names, text='Read the fish name ("<name> x5" fish log)', variable=self.name_read, command=self._on_name_read_toggled).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(names, text="Select name area", command=lambda: self._select_read_area("name_area")).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(names, textvariable=self._name_area_label, style="Muted.TLabel").grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(names, text="Read after (sec)").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self._number_entry(names, "name_read_delay_sec", width=6).grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Button(names, text="Test read", command=self._test_name_read).grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Label(names, text="Catch a fish manually, and while its name is on screen click Select name area, drag the box over the name and press Enter. Test read shows what it reads.", style="Muted.TLabel", wraplength=340, justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._refresh_name_area_label()
        self._build_color_grade(parent, 2)

    def _build_color_grade(self, parent, row: int) -> None:
        box = ttk.LabelFrame(parent, text="Color grade", padding=8)
        box.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 6))
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text="Give a fish a color and its line in the fish log gets that color. Type the name how it shows in game.", style="Muted.TLabel", wraplength=340, justify="left").grid(row=0, column=0, sticky="w")
        self._grade_box = ttk.Frame(box)
        self._grade_box.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(box, text="Add fish", command=self._add_grade_row).grid(row=2, column=0, sticky="w", pady=(6, 0))
        for item in self.cfg["fish_colors"]:
            self._add_grade_row(item["name"], item["color"], save=False)

    def _add_grade_row(self, name: str = "", color: str = "White", save: bool = True) -> None:
        frame = ttk.Frame(self._grade_box)
        frame.pack(fill="x", pady=1)
        row = {"frame": frame, "name": tk.StringVar(value=name), "color": tk.StringVar(value=color), "last": color}
        ttk.Entry(frame, textvariable=row["name"], width=20).pack(side="left")
        combo = ttk.Combobox(frame, textvariable=row["color"], values=[n for n, _ in FISH_COLORS] + [CUSTOM_COLOR], width=9, state="readonly")
        combo.pack(side="left", padx=(6, 0))
        row["swatch"] = tk.Label(frame, width=2, bg="#%06X" % self._swatch(color), relief="solid", bd=1)
        row["swatch"].pack(side="left", padx=(6, 0))
        ttk.Button(frame, text="X", width=3, command=lambda: self._remove_grade_row(row)).pack(side="left", padx=(6, 0))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_grade_color(row))
        row["name"].trace_add("write", lambda *_: self._save_grades())
        self._grade_rows.append(row)
        if save:
            self._save_grades()

    def _swatch(self, color: str) -> int:
        value = _color_value(color)
        return CAUGHT_COLOR if value is None else value

    def _on_grade_color(self, row: dict) -> None:
        color = row["color"].get()
        if color == CUSTOM_COLOR:
            picked = colorchooser.askcolor(color="#%06X" % self._swatch(row["last"]), parent=self, title="Fish color")
            color = picked[1].upper() if picked and picked[1] else row["last"]
            row["color"].set(color)
        row["last"] = color
        row["swatch"].configure(bg="#%06X" % self._swatch(color))
        self._save_grades()

    def _remove_grade_row(self, row: dict) -> None:
        row["frame"].destroy()
        self._grade_rows.remove(row)
        self._save_grades()

    def _save_grades(self) -> None:
        self.cfg["fish_colors"] = [
            {"name": r["name"].get().strip()[:40], "color": r["color"].get()}
            for r in self._grade_rows
            if r["name"].get().strip()
        ]
        self._persist()

    def _grade_mark(self, name: str) -> str:
        for item in self.cfg["fish_colors"]:
            if _same_fish(item["name"], name):
                value = _color_value(item["color"])
                if value is not None:
                    return _square(value)
        return FISH_MARK

    def _build_help_tab(self, parent) -> None:
        picks = ttk.Frame(parent, padding=(6, 6, 6, 0))
        picks.grid(row=0, column=0, columnspan=2, sticky="ew")
        picks.columnconfigure(0, weight=1)
        picks.columnconfigure(1, weight=1)
        for i, (key, title, _text) in enumerate(HELP_TOPICS):
            ttk.Radiobutton(picks, text=title, value=key, variable=self._help_topic, style="Toolbutton", command=self._show_help).grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
        video = ttk.Frame(picks)
        video.grid(row=(len(HELP_TOPICS) + 1) // 2, column=0, columnspan=2, sticky="w", padx=2, pady=(4, 0))
        ttk.Label(video, text="Full setup guide:").pack(side="left")
        self._link_label(video, GUIDE_URL, GUIDE_URL).pack(side="left", padx=(6, 0))
        inner = self._scrollable(parent, 1)
        self._help_box = ttk.LabelFrame(inner, padding=8)
        self._help_box.pack(fill="x", padx=(0, 4))
        self._help_text = ttk.Label(self._help_box, wraplength=340, justify="left")
        self._help_text.pack(anchor="w")
        self._show_help()

    def _show_help(self) -> None:
        for key, title, text in HELP_TOPICS:
            if key == self._help_topic.get():
                self._help_box.configure(text=title)
                self._help_text.configure(text=text)

    def _welcome(self) -> None:
        self.cfg["welcome_done"] = True
        self._persist()
        win, frame, text, row = self._dialog("Welcome", WELCOME_ASK)
        ready = {"open": False}

        def close() -> None:
            if not ready["open"]:
                return
            try:
                win.grab_release()
            except tk.TclError:
                pass
            win.destroy()

        def guide() -> None:
            for child in row.winfo_children():
                child.destroy()
            text.configure(text=WELCOME_GUIDE)
            self._link_label(frame, GUIDE_URL, GUIDE_URL).pack(before=row, pady=(6, 0))
            ttk.Button(row, text="OK", command=close).pack(side="left", padx=6)

        yes = ttk.Button(row, text="Yes", command=guide, state="disabled")
        no = ttk.Button(row, text="No", command=close, state="disabled")
        yes.pack(side="left", padx=6)
        no.pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", close)
        self._show_dialog(win, [(yes, "Yes"), (no, "No")], ready)

    def _run_time(self) -> str:
        run = int(time.monotonic() - self._run_started)
        return f"{run // 3600}:{run // 60 % 60:02d}:{run % 60:02d}"

    def _ping(self, payload: dict) -> dict:
        uid = self.cfg["webhook_user"]
        if uid:
            payload["content"] = f"<@{uid}>"
            payload["allowed_mentions"] = {"users": [uid]}
        else:
            payload["allowed_mentions"] = {"parse": []}
        return payload

    def _test_webhook(self) -> None:
        if not self.cfg["webhook_url"]:
            self._status.set("Paste your webhook URL first.")
            return
        self._status.set("Sending a test to the webhook...")
        payload = self._ping({"embeds": [embed("Webhook works :)", 0x5865F2, [], "Test from " + self.title() + ".")]})
        threading.Thread(target=self._send_webhook, args=(payload, "test"), daemon=True).start()

    def _on_catch(self) -> None:
        self._catches += 1
        self._last_catch = time.monotonic()
        self._fail_sent = False
        self._dc_sent = 0
        if not (self.cfg["webhook_enabled"] and self.cfg["webhook_url"]):
            return
        fields = [("Catch", f"#{self._catches}"), ("Running for", self._run_time())]
        if not (self.cfg["name_read"] and self.cfg.get("name_area")):
            self._send_webhook(self._catch_payload(fields), "catch")
            return
        stop = self._stop_event
        if sleep_interruptible(float(self.cfg["advanced"].get("name_read_delay_sec", 0.1)), stop.is_set):
            return
        try:
            frame = capture_roblox()
        except Exception:
            frame = None
        crop = self._area_crop(frame, "name_area")
        threading.Thread(target=self._send_named_catch, args=(crop,), daemon=True).start()

    def _catch_payload(self, fields: list) -> dict:
        return {"allowed_mentions": {"parse": []}, "embeds": [embed("Fish Caught :)", CAUGHT_COLOR, fields)]}

    def _send_named_catch(self, crop) -> None:
        name = self._name_reader.read(crop)
        url = self.cfg["webhook_url"]
        with self._tally_lock:
            if name:
                what = next((k for k in self._tally if _same_fish(k, name)), name)
                self._tally[what] = self._tally.get(what, 0) + 1
            else:
                self._escaped += 1
                what = "escaped, name not read: %s" % self._name_reader.why
            payload = self._log_payload()
        self._live_log.update(url, payload, lambda msg: self._post(lambda: self._status.set(f"Webhook fish log ({what}): {msg}.")))

    def _log_payload(self) -> dict:
        items = sorted(self._tally.items(), key=lambda kv: -kv[1])
        lines = [f"{self._grade_mark(fish)} {fish} x{n}" for fish, n in items]
        shown: list[str] = []
        for line in lines:
            if len("\n".join(shown + [line])) > LOG_TEXT_MAX:
                break
            shown.append(line)
        if len(shown) < len(lines):
            shown.append(f"...and {len(lines) - len(shown)} more")
        log = embed("Fishing Log", CAUGHT_COLOR, [
            ("Caught", str(sum(self._tally.values()))),
            ("Escaped", str(self._escaped)),
            ("Running for", self._run_time()),
        ], "\n" + ("\n".join(shown) or "No fish yet"))
        return {"allowed_mentions": {"parse": []}, "embeds": [log]}

    def _area_crop(self, frame, key: str):
        area = self.cfg.get(key)
        if frame is None or not area:
            return None
        h, w = frame.shape[:2]
        x0 = max(0, int(round(area["x"] * w)))
        y0 = max(0, int(round(area["y"] * h)))
        x1 = min(w, int(round((area["x"] + area["w"]) * w)))
        y1 = min(h, int(round((area["y"] + area["h"]) * h)))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        return frame[y0:y1, x0:x1].copy()

    def _refresh_name_area_label(self) -> None:
        area = self.cfg.get("name_area")
        if not area:
            self._name_area_label.set("Not set")
        else:
            self._name_area_label.set("Set (%d%% x %d%% of Roblox)" % (round(area["w"] * 100), round(area["h"] * 100)))

    def _on_name_read_toggled(self) -> None:
        self._persist()
        if not self.name_read.get():
            return
        if not self.cfg.get("name_area"):
            self._status.set("Now select the name area (Webhook > Select name area).")
        threading.Thread(target=self._name_reader.warm, daemon=True).start()

    def _refresh_t_area_label(self) -> None:
        self._t_area_label.set("T area: set" if self.cfg.get("t_area") else "T area: not set")

    def _on_t_visual_toggled(self) -> None:
        self._persist()
        if not self.t_visual.get():
            return
        if not self.cfg.get("t_area"):
            self._status.set("Catch a fish manually, click Select T area while T Collect is on screen and drag the box over the whole prompt, a bit bigger so it covers the swing.")
        threading.Thread(target=self._name_reader.warm, daemon=True).start()

    def _open_selector(self, area: dict, what: str, on_saved) -> None:
        if self._running:
            self._status.set(f"Stop first, then select the {what} area.")
            return
        if self._calibrator_open():
            return
        origin = resolve_origin()
        if origin.source != "roblox":
            self._status.set(f"Open Roblox first, the {what} area is saved inside the Roblox window.")
            return
        bounds = origin.as_pixel_rect
        initial = rect_to_screen(area["x"], area["y"], area["w"], area["h"], origin).clamp_within(bounds)
        self._status.set(f"Drag the box over the {what}. Enter saves, Esc cancels.")
        self._area_selector = AreaSelector(
            self,
            initial=initial,
            bounds=bounds,
            on_saved=on_saved,
            on_cancelled=self._on_area_cancelled,
        )
        self._on_hotkey_window_effects(turning_on=True)

    def _saved_area(self, rect: PixelRect) -> dict:
        self._area_selector = None
        origin = resolve_origin()
        fx, fy, fw, fh = clamp_rect(*rect_from_screen(rect, origin))
        self._on_hotkey_window_effects(turning_on=False)
        return {"x": fx, "y": fy, "w": fw, "h": fh}

    def _select_read_area(self, key: str) -> None:
        what = "T Collect prompt" if key == "t_area" else "fish name"
        area = self.cfg.get(key) or READ_AREA_DEFAULTS[key]
        self._open_selector(area, what, lambda rect: self._on_read_area_saved(key, rect))

    def _on_read_area_saved(self, key: str, rect: PixelRect) -> None:
        self.cfg[key] = self._saved_area(rect)
        self._persist()
        self._refresh_name_area_label()
        self._refresh_t_area_label()
        if key == "t_area":
            self._status.set("T area saved. Press Test while the T Collect prompt is on screen.")
        else:
            self._status.set("Name area saved. Press Test read while a fish name is on screen.")

    def _refresh_ignore_rows(self) -> None:
        for child in self._ignore_rows.winfo_children():
            child.destroy()
        for i in range(len(self.cfg["t_ignore"])):
            row = ttk.Frame(self._ignore_rows)
            row.pack(anchor="w", pady=1)
            ttk.Label(row, text=f"Box {i + 1}").pack(side="left")
            ttk.Button(row, text="Change", width=7, command=lambda i=i: self._select_ignore(i)).pack(side="left", padx=(6, 0))
            ttk.Button(row, text="-", width=3, command=lambda i=i: self._remove_ignore(i)).pack(side="left", padx=(4, 0))

    def _select_ignore(self, index: int | None) -> None:
        boxes = self.cfg["t_ignore"]
        area = boxes[index] if index is not None else (self.cfg.get("t_area") or READ_AREA_DEFAULTS["t_area"])
        self._open_selector(area, "text to ignore", lambda rect: self._on_ignore_saved(index, rect))

    def _on_ignore_saved(self, index: int | None, rect: PixelRect) -> None:
        box = self._saved_area(rect)
        if index is None or index >= len(self.cfg["t_ignore"]):
            self.cfg["t_ignore"].append(box)
        else:
            self.cfg["t_ignore"][index] = box
        self._persist()
        self._refresh_ignore_rows()
        self._status.set("Ignore box saved. Text inside it is never read by Visual T collect.")

    def _remove_ignore(self, index: int) -> None:
        if 0 <= index < len(self.cfg["t_ignore"]):
            del self.cfg["t_ignore"][index]
            self._persist()
            self._refresh_ignore_rows()
            self._status.set("Ignore box removed.")

    def _test_name_read(self) -> None:
        if not self.cfg.get("name_area"):
            self._status.set("Select the name area first.")
            return
        self._status.set("Reading the name area...")

        def run() -> None:
            try:
                frame = capture_roblox()
            except Exception:
                frame = None
            crop = self._area_crop(frame, "name_area")
            if crop is None:
                msg = "Roblox not found, open it first."
            else:
                name = self._name_reader.read(crop)
                msg = f"Read: {name}" if name else f"Couldn't read a name ({self._name_reader.why})."
            self._post(lambda: self._status.set(msg))

        threading.Thread(target=run, daemon=True).start()

    def _test_t_read(self) -> None:
        if not self.cfg.get("t_area"):
            self._status.set("Select the T area first.")
            return
        self._status.set("Reading the T area...")

        def run() -> None:
            text, why = self._t_text()
            if text is None:
                msg = f"Couldn't read the T area ({why})."
            elif _letter_chain(text) >= LETTER_CHAIN:
                msg = f"Letters visible (read: {text})"
            else:
                msg = f"No 3+ letters in a row, Visual T collect would let go here (read: {text or 'nothing'})."
            self._post(lambda: self._status.set(msg))

        threading.Thread(target=run, daemon=True).start()

    def _t_crop(self, frame):
        crop = self._area_crop(frame, "t_area")
        area = self.cfg.get("t_area")
        if crop is None or not self.cfg["t_ignore"]:
            return crop
        h, w = frame.shape[:2]
        ax, ay = int(round(area["x"] * w)), int(round(area["y"] * h))
        fill = crop.reshape(-1, crop.shape[2]).mean(axis=0)
        for box in self.cfg["t_ignore"]:
            x0 = max(0, int(round(box["x"] * w)) - ax)
            y0 = max(0, int(round(box["y"] * h)) - ay)
            x1 = min(crop.shape[1], int(round((box["x"] + box["w"]) * w)) - ax)
            y1 = min(crop.shape[0], int(round((box["y"] + box["h"]) * h)) - ay)
            if x1 > x0 and y1 > y0:
                crop[y0:y1, x0:x1] = fill
        return crop

    def _t_text(self) -> tuple[str | None, str]:
        try:
            frame = capture_roblox()
        except Exception:
            frame = None
        crop = self._t_crop(frame)
        if crop is None:
            return None, "Roblox not found, open it first"
        return self._name_reader.read_text(crop)

    def _t_visible(self) -> bool | None:
        text, _why = self._t_text()
        if text is None:
            return None
        return _letter_chain(text) >= LETTER_CHAIN

    def _fail_watch(self, stop: threading.Event) -> None:
        while not stop.wait(1.0):
            if not self.cfg["webhook_url"]:
                continue
            idle = time.monotonic() - self._last_catch
            if self.cfg["webhook_dc"] and idle >= (self._dc_sent + 1) * WEBHOOK_DC_SEC:
                payload = self._ping({"embeds": [embed(
                    "Possibly disconnected OR griefed", 0xED4245,
                    [("Catches", str(self._catches)), ("Running for", self._run_time())],
                    f"No fish caught in the last {int(idle) // 60} minutes.",
                )]})
                if self._send_webhook(payload, "disconnect alert"):
                    self._dc_sent = int(idle // WEBHOOK_DC_SEC)
                continue
            if self._fail_sent or not self.cfg["webhook_fail"] or idle < WEBHOOK_FAIL_SEC:
                continue
            payload = self._ping({"embeds": [embed(
                "Something failed :(", 0xED4245,
                [("Catches", str(self._catches)), ("Running for", self._run_time())],
                f"No fish caught in the last {WEBHOOK_FAIL_SEC} seconds.",
            )]})
            self._fail_sent = self._send_webhook(payload, "fail alert")

    def _send_webhook(self, payload: dict, what: str) -> bool:
        try:
            frame = capture_roblox()
        except Exception:
            frame = None

        def report(msg: str) -> None:
            self._post(lambda: self._status.set(f"Webhook {what}: {msg}."))

        if self._webhook.send(self.cfg["webhook_url"], payload, frame, report):
            return True
        report("still sending the last one, skipped")
        return False

    def _build_notes_tab(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        box = ttk.LabelFrame(parent, text="Notes", padding=8)
        box.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ttk.Label(box, text=NOTES_TOP, wraplength=360, justify="left").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(box, text=NOTES_TEXT, wraplength=360, justify="left").grid(row=1, column=0, sticky="w")

    def _build_advanced_tab(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        head = ttk.Frame(parent, padding=(6, 6, 6, 0))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Saves as you type, Reset defaults fixes anything you mess up", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(head, text="Reset defaults", command=self._reset_advanced).grid(row=0, column=1, sticky="e")

        inner = self._scrollable(parent, 1)

        for section_title, fields in ADVANCED_SECTIONS:
            box = ttk.LabelFrame(inner, text=section_title, padding=6)
            box.pack(fill="x", pady=(0, 6), padx=(0, 4))
            box.columnconfigure(2, weight=1)
            for r, (key, label, help_text) in enumerate(fields):
                ttk.Label(box, text=label).grid(row=r, column=0, sticky="w", pady=1)
                self._number_entry(box, key, width=7).grid(row=r, column=1, sticky="w", padx=6)
                ttk.Label(box, text=help_text, style="Muted.TLabel", wraplength=200, justify="left").grid(row=r, column=2, sticky="w")

    def _reset_advanced(self) -> None:
        for key, var in self._advanced_vars.items():
            var.set(str(DEFAULT_ADVANCED[key]))
        self._apply_runtime_settings()
        self._status.set("Advanced settings reset to defaults.")

    def _collect_advanced(self) -> dict[str, float]:
        out = dict(self.cfg["advanced"])
        for key, var in self._advanced_vars.items():
            try:
                value = float(var.get())
            except ValueError:
                continue
            if key in SHARED_NUMBERS:
                value = max(NUMBER_MIN.get(key, 0.0), value)
            out[key] = value
        return out

    def _apply_runtime_settings(self) -> None:
        adv = self.cfg["advanced"]
        apply_mouse_timings(
            nudge_mid_sec=adv["mouse_nudge_mid_sec"],
            nudge_settle_sec=adv["mouse_nudge_settle_sec"],
            click_hold_sec=adv["mouse_click_hold_sec"],
        )
        self._tracker.configure(adv)
        self._scanner.configure(self.cfg.get("bar_colors"), adv["yellow_boost"], adv["green_boost"], adv["white_boost"])

    def _persist(self) -> None:
        if self._persisting:
            return
        self._persisting = True
        try:
            self.cfg["hotkeys"] = {kid: var.get() for kid, var in self._hotkey_vars.items()}
            self.cfg["show_scan_outline"] = bool(self.show_scan_outline.get())
            self.cfg["show_overlay_arrows"] = bool(self.show_overlay_arrows.get())
            self.cfg["show_fps_overlay"] = bool(self.show_fps_overlay.get())
            self.cfg["auto_minimize"] = bool(self.auto_minimize.get())
            self.cfg["auto_focus_roblox"] = bool(self.auto_focus_roblox.get())
            self.cfg["always_on_top"] = bool(self.always_on_top.get())
            self.cfg["collect_hold_t"] = bool(self.collect_hold_t.get())
            self.cfg["drop_fish"] = bool(self.drop_fish.get())
            self.cfg["worm_bait"] = bool(self.worm_bait.get())
            self.cfg["webhook_enabled"] = bool(self.webhook_enabled.get())
            self.cfg["webhook_url"] = self.webhook_url.get().strip()
            self.cfg["webhook_fail"] = bool(self.webhook_fail.get())
            self.cfg["webhook_dc"] = bool(self.webhook_dc.get())
            self.cfg["webhook_user"] = _digits(self.webhook_user.get())
            self.cfg["name_read"] = bool(self.name_read.get())
            self.cfg["t_visual"] = bool(self.t_visual.get())
            snap = self._quest_snapshot()
            self.cfg.setdefault("quest_levels", {})[str(snap["level"])] = snap
            self.cfg["quest"] = {k: v for k, v in snap.items() if k != "points"}
            self.cfg["move_enabled"] = bool(self.move_enabled.get())
            self.cfg["move"] = merge_move({k: {"on": on.get(), "sec": sec.get()} for k, (on, sec) in self._move.items()})
            self.cfg["free_mouse"] = bool(self.free_mouse.get())
            self.cfg["rod_key"] = str(self.rod_key.get()).strip()[:12]
            self.cfg["advanced"] = self._collect_advanced()
            save_config(self.cfg)
        finally:
            self._persisting = False

    def _point_summary(self, key: str) -> str:
        raw = (self.cfg.get("points") or {}).get(key) or {}
        try:
            return f"({float(raw['x']):.3f}, {float(raw['y']):.3f})"
        except (KeyError, TypeError, ValueError):
            return "(unset)"

    def _refresh_point_summaries(self) -> None:
        self._cast_point_label.set(self._point_summary("cast"))
        self._refresh_collect_ui()
        self._refresh_quest_ui()

    def _on_collect_mode_toggle(self) -> None:
        self._persist()
        self._refresh_collect_ui()

    def _refresh_collect_ui(self) -> None:
        if self.collect_hold_t.get():
            self._collect_point_label.set("holds the T key")
            self._collect_select_btn.configure(state="disabled")
        else:
            self._collect_point_label.set(self._point_summary("collect"))
            self._collect_select_btn.configure(state="normal")

    def _on_auto_minimize_toggled(self) -> None:
        self._persist()
        if not self.auto_minimize.get() and not self._running:
            restore_tk(self, keep_topmost=bool(self.always_on_top.get()), activate=False)

    def _on_free_mouse_toggled(self) -> None:
        self._persist()
        if self.free_mouse.get():
            self._status.set("Free mouse on. Turn on shiftlock in Roblox.")
        else:
            self._status.set("Free mouse off.")
        self._apply_free_mouse()

    def _apply_free_mouse(self) -> None:
        if not self.free_mouse.get():
            self._free_mouse.stop()
            return
        if not self._free_mouse.start():
            self._free_mouse_failed()
            return
        self.after(800, self._check_free_mouse)

    def _check_free_mouse(self) -> None:
        if self.free_mouse.get() and not self._free_mouse.running and not self._closing:
            self._free_mouse_failed()

    def _free_mouse_failed(self) -> None:
        self.free_mouse.set(False)
        self._persist()
        self._status.set("Free mouse couldn't start on this PC.")

    def _on_always_on_top_toggled(self) -> None:
        self._persist()
        self._apply_always_on_top()

    def _apply_always_on_top(self) -> None:
        pin_topmost_no_activate(self, bool(self.always_on_top.get()))

    def _minimize_gui(self) -> None:
        try:
            minimize_tk(self)
        except tk.TclError:
            pass

    def _restore_gui(self, *, activate: bool = True) -> None:
        restore_tk(self, keep_topmost=bool(self.always_on_top.get()), activate=activate)

    def _focus_roblox_keep_gui_on_top(self) -> None:
        focus_roblox()
        pin_topmost_no_activate(self, True)

    def _on_hotkey_window_effects(self, *, turning_on: bool) -> None:
        auto_min = bool(self.auto_minimize.get())
        auto_focus = bool(self.auto_focus_roblox.get())
        on_top = bool(self.always_on_top.get())

        if turning_on:
            if auto_min:
                self.after(30, self._minimize_gui)
            if auto_focus:
                delay = 120 if auto_min else 40
                if on_top and not auto_min:
                    self.after(delay, self._focus_roblox_keep_gui_on_top)
                else:
                    self.after(delay, focus_roblox)
            elif on_top and not auto_min:
                self.after(40, self._apply_always_on_top)
            return

        if auto_min:
            self.after(0, lambda: self._restore_gui(activate=True))
        if on_top:
            delay = 80 if auto_min else 0
            self.after(delay, self._apply_always_on_top)

    def _calibrator_open(self) -> bool:
        if self._area_selector is not None and self._area_selector.winfo_exists():
            return True
        if self._click_capture is not None and self._click_capture.winfo_exists():
            return True
        if self._bar_drawer is not None and self._bar_drawer.winfo_exists():
            return True
        if self._bar_record_stop is not None:
            return True
        return False

    def _capture_point(self, key: str, *, then=None) -> None:
        if self._running:
            self._status.set("Stop first, then set points.")
            return
        if self._calibrator_open():
            self._status.set("Finish the current adjust first.")
            return

        label = POINT_LABELS.get(key, key)
        self._status.set(f"Click to set: {label}...")

        def on_saved(pt: FracPoint, source: str) -> None:
            self._click_capture = None
            self.cfg.setdefault("points", {})[key] = {"x": pt.x, "y": pt.y}
            self._persist()
            self._refresh_point_summaries()
            self._status.set(f"{label} saved ({source}).")
            if then:
                self.after(80, then)

        def on_cancelled() -> None:
            self._click_capture = None
            self._status.set("Point set cancelled.")

        self._click_capture = ClickCapture(
            self,
            prompt=f"Set: {label}",
            on_saved=on_saved,
            on_cancelled=on_cancelled,
        )

    def _on_overlay_toggles(self) -> None:
        self._persist()
        if self._running:
            self._show_runtime_overlays()
        if not self.show_overlay_arrows.get():
            self._zone_marker.hide()
            self._green_markers.hide()
            self._white_marker.hide()
        if not self.show_fps_overlay.get():
            self._fps_overlay.hide()
        if not (self.show_scan_outline.get() or self.show_overlay_arrows.get() or self.show_fps_overlay.get()):
            self._perf_hint.hide()

    def _show_runtime_overlays(self) -> None:
        try:
            rect = scan_rect_screen(self.cfg)
        except Exception:
            return
        if self.show_scan_outline.get():
            self._scan_outline.update(rect)
        else:
            self._scan_outline.hide()

    def _hide_track_markers(self) -> None:
        self._zone_marker.hide()
        self._green_markers.hide()
        self._white_marker.hide()
        self._fps_overlay.hide()
        self._perf_hint.hide()

    def _hide_task_overlays(self) -> None:
        self._scan_outline.hide()
        for m in (self._zone_marker, self._green_markers, self._white_marker, self._fps_overlay, self._perf_hint):
            destroy = getattr(m, "destroy", None)
            if callable(destroy):
                destroy()
            else:
                m.hide()
        self._overlay_pending = None

    def _start_run(self) -> bool:
        quest = self._mode() == "quest"
        if quest and not quest_points_set(self.cfg):
            self._status.set("Set the quest positions first (Fishing Quest > 1. Positions).")
            return False
        if not quest and not cast_point_set(self.cfg):
            self._status.set("Select the cast point first (2. Cast > Select cast point).")
            return False
        self._persist()
        self._apply_runtime_settings()
        old = self._worker
        if old is not None and old.is_alive():
            old.join(timeout=1.0)
        self._running = True
        self._stop_event = threading.Event()
        self._tracker.reset()
        self._lag_detector.reset()
        self._click.release()
        if not quest:
            self._show_runtime_overlays()
        self._perf_hint.hide()
        self._status.set("Starting fishing quest..." if quest else "Starting fishing cycle...")
        self._start_btn.configure(text="Press To Stop (F1)")
        self._catches = 0
        self._run_started = time.monotonic()
        self._last_catch = self._run_started
        self._fail_sent = False
        self._dc_sent = 0
        with self._tally_lock:
            self._tally = {}
            self._escaped = 0
        self._live_log.reset()
        if (self.cfg["name_read"] and self.cfg["webhook_enabled"]) or self.cfg["t_visual"]:
            threading.Thread(target=self._name_reader.warm, daemon=True).start()
        self._worker = threading.Thread(target=self._quest_loop if quest else self._automation_loop, args=(self._stop_event,), daemon=True)
        self._worker.start()
        if not quest:
            threading.Thread(target=self._fail_watch, args=(self._stop_event,), daemon=True).start()
        return True

    def _stop_run(self) -> None:
        self._running = False
        self._stop_event.set()
        self._click.release()
        release_inputs()
        self._tracker.reset()
        self._hide_task_overlays()
        self._status.set("Stopped.")
        self._start_btn.configure(text="Press To Start (F1)")

    def _perf_hint_text(self) -> str:
        any_overlay = self.show_scan_outline.get() or self.show_overlay_arrows.get() or self.show_fps_overlay.get()
        return PerfHintOverlay.HINT_WITH_OVERLAYS if any_overlay else PerfHintOverlay.HINT_FPS_ONLY

    def _unregister_hotkeys(self) -> None:
        for handle in self._hotkey_handles:
            try:
                platform_keys.remove_hotkey(handle)
            except Exception:
                pass
        self._hotkey_handles.clear()

    def _register_hotkeys(self) -> None:
        self._unregister_hotkeys()
        mapping = {
            "hotkey_1": self._on_hotkey_start_stop,
            "hotkey_2": self._on_hotkey_adjust_area,
            "hotkey_3": self._on_hotkey_bar_colors,
            "hotkey_4": self._on_hotkey_exit,
        }
        for key_id, callback in mapping.items():
            name = self._hotkey_vars[key_id].get()
            try:
                handle = platform_keys.add_hotkey(name, lambda cb=callback: self._post(cb))
                self._hotkey_handles.append(handle)
            except Exception as exc:
                self._status.set(f"Couldn't bind {HOTKEY_LABELS[key_id]}: {exc}")

    def _on_hotkey_start_stop(self) -> None:
        if self._listening_for is not None:
            return
        if self._calibrator_open():
            self._status.set("Finish adjusting / setting points first.")
            return
        if self._running:
            self._stop_run()
            self._on_hotkey_window_effects(turning_on=False)
        elif self._start_run():
            self._on_hotkey_window_effects(turning_on=True)

    def _queue_overlay(
        self,
        rect: PixelRect,
        mid_x: int | None,
        green_top: int | None,
        green_bot: int | None,
        white_y: int | None,
        fps: float | None,
        show_hint: bool = False,
    ) -> None:
        if IS_MAC:
            return
        self._overlay_pending = (rect, mid_x, green_top, green_bot, white_y, fps, show_hint)
        if not self._overlay_scheduled:
            self._overlay_scheduled = True
            self._post(self._flush_overlay)

    def _post(self, fn) -> None:
        self._posted.put(fn)

    def _pump_posted(self) -> None:
        if self._closing:
            return
        try:
            for _ in range(64):
                try:
                    fn = self._posted.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception as exc:
                    self._status.set(f"Error: {exc}")
        finally:
            self.after(15, self._pump_posted)

    def _flush_overlay(self) -> None:
        self._overlay_scheduled = False
        pending = self._overlay_pending
        if pending is None or not self._running or self._closing:
            return
        rect, mid_x, green_top, green_bot, white_y, fps, show_hint = pending
        try:
            if show_hint:
                self._perf_hint.update(rect, self._perf_hint_text())
            else:
                self._perf_hint.hide()
            if self.show_overlay_arrows.get():
                self._zone_marker.update(rect, mid_x)
                self._green_markers.update(rect, green_top, green_bot)
                self._white_marker.update(rect, white_y)
            else:
                self._zone_marker.hide()
                self._green_markers.hide()
                self._white_marker.hide()
            if self.show_fps_overlay.get():
                self._fps_overlay.update(rect, fps)
            else:
                self._fps_overlay.hide()
        except tk.TclError:
            pass
        if self._overlay_pending is not pending and self._running:
            self._overlay_scheduled = True
            self.after(1, self._flush_overlay)

    def _automation_loop(self, stop: threading.Event) -> None:
        def aborted() -> bool:
            return stop.is_set() or self._closing

        def status(msg: str) -> None:
            self._post(lambda m=msg: None if stop.is_set() else self._status.set(m))

        try:
            while not aborted():
                self._post(self._show_runtime_overlays)
                try:
                    run_one_cycle(
                        cfg=self.cfg,
                        scanner=self._scanner,
                        tracker=self._tracker,
                        click=self._click,
                        should_abort=aborted,
                        set_status=status,
                        queue_overlay=self._queue_overlay,
                        lag_observe=self._lag_detector.observe,
                        on_catch=self._on_catch,
                        t_visible=self._t_visible if self.cfg["t_visual"] and self.cfg.get("t_area") else None,
                    )
                except Exception as exc:
                    self._click.release()
                    release_inputs()
                    status(f"Cycle error, restarting: {exc}")
                    if sleep_interruptible(CYCLE_ERROR_PAUSE_SEC, aborted):
                        break
                    continue
                if aborted():
                    break
                self._post(self._hide_track_markers)
        finally:
            self._click.release()
            release_inputs()
            if stop.is_set() or self._closing:
                self._post(self._hide_task_overlays)
            else:
                self._post(self._on_worker_ended)

    def _quest_loop(self, stop: threading.Event) -> None:
        def aborted() -> bool:
            return stop.is_set() or self._closing

        def status(msg: str) -> None:
            self._post(lambda m=msg: None if stop.is_set() else self._status.set(m))

        done = 0
        try:
            while not aborted():
                try:
                    ok = run_quest_cycle(self.cfg, aborted, status)
                except Exception as exc:
                    release_inputs()
                    status(f"Quest error, restarting: {exc}")
                    if sleep_interruptible(CYCLE_ERROR_PAUSE_SEC, aborted):
                        break
                    continue
                if ok:
                    done += 1
                    delay = merge_quest(self.cfg.get("quest"))["quest_delay_sec"]
                    status(f"Quest done ({done}). Next quest in {delay:g}s...")
                    if sleep_interruptible(delay, aborted):
                        break
                elif sleep_interruptible(0.5, aborted):
                    break
        finally:
            release_inputs()
            if not (stop.is_set() or self._closing):
                self._post(self._on_worker_ended)

    def _on_worker_ended(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        self._hide_task_overlays()
        self._start_btn.configure(text="Press To Start (F1)")
        self._status.set("The run stopped on its own. Press F1 to start again.")

    def _on_hotkey_adjust_area(self) -> None:
        if self._listening_for is not None:
            return
        if self._area_selector is not None and self._area_selector.winfo_exists():
            self._area_selector.cancel()
            self._on_hotkey_window_effects(turning_on=False)
            return
        if self._running:
            self._status.set("Stop first, then adjust the area.")
            return
        self._open_area_selector()
        self._on_hotkey_window_effects(turning_on=True)

    def _open_area_selector(self) -> None:
        if self._area_selector is not None and self._area_selector.winfo_exists():
            return
        origin = resolve_origin()
        bounds = origin.as_pixel_rect
        if origin.source != "roblox":
            bounds = virtual_screen_rect()
            self._status.set("Roblox not found. Adjusting on the screen; open Roblox for window coords.")
        else:
            self._status.set("Adjust scan area. Enter saves, Esc or F2 cancels.")
        sa = scan_area_from_cfg(self.cfg)
        initial = rect_to_screen(sa.x, sa.y, sa.w, sa.h, origin).clamp_within(bounds)
        self._area_selector = AreaSelector(
            self,
            initial=initial,
            bounds=bounds,
            on_saved=self._on_area_saved,
            on_cancelled=self._on_area_cancelled,
        )

    def _on_area_saved(self, rect: PixelRect) -> None:
        self._area_selector = None
        origin = resolve_origin()
        fx, fy, fw, fh = clamp_rect(*rect_from_screen(rect, origin))
        self.cfg["scan_area"] = {"x": fx, "y": fy, "w": fw, "h": fh}
        self._persist()
        self._on_hotkey_window_effects(turning_on=False)
        self._status.set(
            f"Scan area saved: {rect.w}x{rect.h} at ({rect.x}, {rect.y}) [{origin.source}]."
        )

    def _on_area_cancelled(self) -> None:
        self._area_selector = None
        self._on_hotkey_window_effects(turning_on=False)
        self._status.set("Adjust cancelled.")

    def _refresh_bar_colors_label(self) -> None:
        colors = self.cfg.get("bar_colors")
        if colors:
            self._bar_colors_label.set("Bar colors: custom (from Color Detect)")
        else:
            self._bar_colors_label.set("Bar colors: default")

    def _reset_bar_colors(self) -> None:
        self.cfg["bar_colors"] = None
        self._persist()
        self._apply_runtime_settings()
        self._refresh_bar_colors_label()
        self._status.set("Bar colors back to default.")

    def _on_hotkey_bar_colors(self) -> None:
        if self._listening_for is not None:
            return
        if self._bar_record_stop is not None:
            self._bar_record_stop.set()
            return
        if self._bar_drawer is not None and self._bar_drawer.winfo_exists():
            self._bar_drawer.cancel()
            return
        if self._running:
            self._status.set("Stop first, then fish manually and press this while the minigame is up.")
            return
        if self._calibrator_open():
            self._status.set("Finish the current adjust first.")
            return
        origin = resolve_origin()
        if origin.source != "roblox":
            self._status.set("Open Roblox first, then fish manually and press this while the minigame is up.")
            return
        stop = threading.Event()
        self._bar_record_stop = stop
        bounds = origin.as_pixel_rect
        self._status.set("Recording the bar for %d seconds, keep fishing..." % RECORD_SEC)
        self._record_tick(bounds, RECORD_SEC)

        def tick(left: float, _frames: int) -> None:
            self._post(lambda: self._record_tick(bounds, left))

        def run() -> None:
            first, shots = record(capture_roblox, stop, tick)
            self._post(lambda: self._on_bar_recorded(first, shots, origin, stop.is_set()))

        threading.Thread(target=run, daemon=True).start()

    def _record_tick(self, bounds: PixelRect, left: float) -> None:
        if self._bar_record_stop is None or self._closing:
            return
        try:
            self._record_banner.show(bounds, "Recording the bar, keep fishing and let the ball leave the zone too... %d" % int(left + 0.999))
        except tk.TclError:
            pass

    def _on_bar_recorded(self, first, shots, origin, cancelled: bool) -> None:
        self._bar_record_stop = None
        self._record_banner.hide()
        if self._closing:
            return
        if cancelled:
            self._status.set("Bar color detect cancelled.")
            return
        if first is None or not shots:
            self._status.set("Couldn't capture Roblox, make sure it's open and not minimized.")
            return
        sa = scan_area_from_cfg(self.cfg)
        initial = rect_to_screen(sa.x, sa.y, sa.w, sa.h, origin)
        self._status.set("Drag a box over the fishing bar. Enter saves, Esc cancels.")
        self._bar_drawer = BarDrawer(
            self,
            first,
            origin.as_pixel_rect,
            on_saved=lambda rect: self._on_bar_drawn(rect, shots, origin),
            on_cancelled=self._on_bar_cancelled,
            initial=initial,
        )

    def _on_bar_drawn(self, rect: PixelRect, shots, origin) -> None:
        self._bar_drawer = None
        stop = threading.Event()
        self._bar_record_stop = stop
        self._status.set("Checking the recording...")
        adv = self.cfg["advanced"]
        yellow, green, white = adv["yellow_boost"], adv["green_boost"], adv["white_boost"]

        def progress(k: int, n: int) -> None:
            self._post(lambda: None if stop.is_set() else self._status.set("Checking the recording... %d/%d" % (k, n)))

        def run() -> None:
            try:
                crops = crops_from_shots(shots, rect, origin.as_pixel_rect)
                result = measure(crops, yellow, stop, progress, green, white)
            except Exception as exc:
                result = (None, False, "Bar color detect failed: %s" % exc)
            self._post(lambda: self._on_bar_checked(rect, origin, result))

        threading.Thread(target=run, daemon=True).start()

    def _on_bar_checked(self, rect: PixelRect, origin, result) -> None:
        self._bar_record_stop = None
        if self._closing:
            return
        colors, ok, msg = result
        if ok:
            fx, fy, fw, fh = clamp_rect(*rect_from_screen(rect, origin))
            self.cfg["scan_area"] = {"x": fx, "y": fy, "w": fw, "h": fh}
            self.cfg["bar_colors"] = colors
            self._persist()
            self._apply_runtime_settings()
            self._refresh_bar_colors_label()
        self._status.set(msg)

    def _on_bar_cancelled(self) -> None:
        self._bar_drawer = None
        self._status.set("Bar color detect cancelled.")

    def _on_hotkey_exit(self) -> None:
        if self._listening_for is not None:
            return
        self._on_close()

    def _start_listen(self, key_id: str) -> None:
        if self._listening_for is not None:
            same = self._listening_for == key_id
            self._stop_listen("Hotkey change cancelled.")
            if same:
                return
        self._listening_for = key_id
        self._hotkey_btns[key_id].configure(text="Press a key")
        self._listen_timer = self.after(LISTEN_TIMEOUT_MS, lambda: self._stop_listen("Hotkey change timed out."))
        self._status.set(f"Press a key for {HOTKEY_LABELS[key_id]}... (Esc or a click cancels)")
        self.focus_force()

    def _stop_listen(self, message: str | None = None) -> None:
        if self._listening_for is None:
            return
        self._hotkey_btns[self._listening_for].configure(text="Change")
        self._listening_for = None
        if self._listen_timer is not None:
            self.after_cancel(self._listen_timer)
            self._listen_timer = None
        if message:
            self._status.set(message)

    def _on_any_click(self, event: tk.Event) -> None:
        if self._listening_for is not None and event.widget is not self._hotkey_btns.get(self._listening_for):
            self._stop_listen("Hotkey change cancelled.")

    def _on_key_press(self, event: tk.Event) -> str | None:
        if self._listening_for is None:
            return None
        if isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Spinbox)):
            self._stop_listen("Hotkey change cancelled.")
            return None
        if event.keysym == "Escape":
            self._stop_listen("Hotkey change cancelled.")
            return "break"
        new_key = normalize_key(event)
        if new_key is None:
            self._status.set("That key can't be used. Try another.")
            return "break"
        key_id = self._listening_for
        for other_id, var in self._hotkey_vars.items():
            if other_id != key_id and var.get().upper() == new_key.upper():
                messagebox.showwarning(
                    "Hotkey in use",
                    f'"{new_key}" is already assigned to {HOTKEY_LABELS[other_id]}.',
                    parent=self,
                )
                return "break"
        self._hotkey_vars[key_id].set(new_key)
        self._stop_listen()
        self._persist()
        self._register_hotkeys()
        self._status.set(f"{HOTKEY_LABELS[key_id]} set to {new_key}.")
        return "break"

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._stop_event.set()
        self._running = False
        self._click.release()
        release_inputs()
        self._tracker.reset()
        self._hide_task_overlays()
        if self._area_selector is not None and self._area_selector.winfo_exists():
            try:
                self._area_selector.cancel()
            except Exception:
                pass
        if self._click_capture is not None and self._click_capture.winfo_exists():
            try:
                self._click_capture.cancel()
            except Exception:
                pass
        if self._bar_drawer is not None and self._bar_drawer.winfo_exists():
            try:
                self._bar_drawer.cancel()
            except Exception:
                pass
        if self._bar_record_stop is not None:
            self._bar_record_stop.set()
        self._record_banner.destroy()
        self._unregister_hotkeys()
        self._name_reader.stop()
        self._free_mouse.stop()
        try:
            platform_keys.unhook_all()
        except Exception:
            pass
        self._persist()
        self.destroy()


def main() -> None:
    ensure_dpi_awareness()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
