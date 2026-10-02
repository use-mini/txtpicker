#!/usr/bin/env python3
"""txtpicker: press a shortcut, pick a snippet, have it pasted where you were typing.

The snippet is copied to the clipboard and then pasted: directly with wtype on
Hyprland, and through the RemoteDesktop portal on GNOME and others, where the
daemon does it. `txtpicker menu` opens the picker window; `txtpicker daemon`
holds the global shortcut and runs until you log out.

Two processes, one program: the daemon blocks waiting for the shortcut, so it
cannot also run a GTK main loop. When the shortcut fires it starts
`txtpicker menu` and waits for it.

Files written: ~/.config/txtpicker/{config,snippets.txt},
~/.local/state/txtpicker/, and (GNOME, only while the daemon runs) a hidden
launcher entry in ~/.local/share/applications.
"""
import fcntl
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import time

APP_ID = "io.github.TxtPicker"
DEFAULT_SHORTCUT = "Super+Shift+V"
DEFAULT_FILTER = "both"
DEFAULT_FILTER_KEY = "Ctrl+F"
FILTER_MODES = ("both", "label", "text")
MODE_NAMES = {"both": "label+text", "label": "label", "text": "text"}
AUTO = "auto"
FALLBACK_PASTE = "Ctrl+V"
DEFAULT_PASTE = "auto, Ctrl+V, Ctrl+Shift+V"

MODES = ("normal", "emacs")
DEFAULT_MODE = "normal"

# What each mode binds. Anything not listed here is left to GTK, which is how
# normal mode keeps Ctrl+A as select-all and Home/End/arrows as themselves.
NORMAL_KEYS = {
    "next": "Down",
    "previous": "Up",
    "page_down": "Page_Down",
    "page_up": "Page_Up",
    "accept": "Return, KP_Enter",
    "quit": "Escape",
    "cycle_filter": "Ctrl+Shift+F",
    "cycle_paste": "Ctrl+Shift+P",
    "cycle_mode": "Tab",
}
EMACS_KEYS = {
    **NORMAL_KEYS,
    "next": "Down, Ctrl+N",
    "previous": "Up, Ctrl+P",
    "quit": "Escape, Ctrl+G",
    "beginning": "Ctrl+A",
    "end": "Ctrl+E",
    "forward_char": "Ctrl+F",
    "backward_char": "Ctrl+B",
    "forward_word": "Alt+F",
    "backward_word": "Alt+B",
    "kill_to_end": "Ctrl+K",
    "kill_region": "Ctrl+W",
    "set_mark": "Ctrl+Space",
}
# Dispatch order, so a key bound to two actions resolves predictably.
ACTIONS = ("cycle_filter", "cycle_paste", "cycle_mode", "quit", "accept",
           "next", "previous", "page_down", "page_up", "set_mark", "kill_region",
           "kill_to_end", "beginning", "end", "forward_word", "backward_word",
           "forward_char", "backward_char")

DEFAULTS = {
    "shortcut": DEFAULT_SHORTCUT,
    "filter": DEFAULT_FILTER,
    "paste": DEFAULT_PASTE,
    "mode": DEFAULT_MODE,
}

CONFIG_TEMPLATE = (
    "# Shortcut that opens the snippet menu, e.g. Super+Shift+V or Ctrl+Alt+space\n"
    "# After changing it, run: txtpicker restart\n"
    f"shortcut = {DEFAULT_SHORTCUT}\n"
    "\n"
    "# What typing in the search box matches: both | label | text\n"
    "# Cycling the filter in the menu is remembered for the rest of the session;\n"
    "# logging out, rebooting or `txtpicker restart` comes back to this line.\n"
    f"filter = {DEFAULT_FILTER}\n"
    "\n"
    "# Keystrokes that paste the snippet. The menu cycles through them with\n"
    "# paste_key and remembers the one you picked with for the rest of the session.\n"
    '# "auto" means Ctrl+Shift+V in terminals and Ctrl+V everywhere else; add your\n'
    "# own, e.g. Ctrl+Y to yank in emacs:\n"
    "#   paste = auto, Ctrl+V, Ctrl+Shift+V, Ctrl+Y\n"
    "# Only Hyprland can tell which app is focused, so elsewhere (GNOME, KDE)\n"
    '# "auto" just means Ctrl+V — pick a keystroke explicitly to override it.\n'
    f"paste = {DEFAULT_PASTE}\n"
    "\n"
    "# Keys in the menu: normal | emacs\n"
    "# normal is what your other apps use. emacs adds Ctrl+A/E/F/B, Alt+F/B,\n"
    "# Ctrl+K/W/G/N/P and Ctrl+Space to set the mark (movement then selects).\n"
    "# Tab switches between them while the menu is open, and the switch is\n"
    "# remembered for the rest of the session.\n"
    f"mode = {DEFAULT_MODE}\n"
    "\n"
    "# Any binding can be overridden below, in both modes, with a comma-separated\n"
    "# list. Actions:\n"
    "#   next previous page_down page_up accept quit\n"
    "#   beginning end forward_char backward_char forward_word backward_word\n"
    "#   kill_to_end kill_region set_mark cycle_filter cycle_paste cycle_mode\n"
    "#key.next = Down, Ctrl+N\n"
    "#key.cycle_mode = Tab\n"
)

SNIPPETS_TEMPLATE = (
    '# One snippet per line. "label :: text" shows the label, copies the text.\n'
    "# Use \\n for a new line and \\t for a tab.\n"
    "my.email@example.com\n"
    "Thanks for your message! I'll get back to you soon.\n"
    "Signature :: Best regards,\\nYour Name\n"
)

# The wrapper hands us a GTK environment. Children that are not us have no use
# for it, and an inherited LD_PRELOAD would pull GTK into the user's $EDITOR.
GTK_ENV_VARS = ("LD_PRELOAD", "GI_TYPELIB_PATH", "GSETTINGS_SCHEMA_DIR",
                "GDK_PIXBUF_MODULE_FILE")


MESSAGES = []  # also shown in the menu's error line; the daemon's stderr is invisible


def log(message):
    MESSAGES.append(message)
    print(f"txtpicker: {message}", file=sys.stderr, flush=True)


def notify(message):
    try:
        subprocess.run(["notify-send", "txtpicker", message], env=child_env(),
                       stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass


def die(message):
    log(message)
    notify(message)
    sys.exit(1)


def child_env(**extra):
    """The environment for a child process, without our GTK wrapping.

    Spawning ourselves is safe too: the wrapper puts it all back.
    """
    environment = {k: v for k, v in os.environ.items() if k not in GTK_ENV_VARS}
    environment.update(extra)
    return environment


def self_path():
    """Our own command: the wrapper when installed, this file from a checkout.

    It has to be the wrapper — argv[0] and __file__ both point inside it, at the
    unwrapped script, which would start without the GTK environment.
    """
    return shutil.which("txtpicker") or os.path.abspath(__file__)


# ── paths ───────────────────────────────────────────────────────────────────
# Functions, not constants: the environment is the source of truth, and tests
# and `systemd-run` both change it under us.

def _xdg(variable, fallback):
    return os.environ.get(variable) or os.path.expanduser(fallback)


def config_dir():
    return os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), "txtpicker")


def config_file():
    return os.path.join(config_dir(), "config")


def snippets_file():
    return os.environ.get("TXTPICKER_FILE") or os.path.join(config_dir(), "snippets.txt")


def state_dir():
    return os.path.join(_xdg("XDG_STATE_HOME", "~/.local/state"), "txtpicker")


def token_file():
    return os.path.join(state_dir(), "remote-desktop-token")


def session_file():
    # In the runtime dir, not the state dir: what the menu remembers is meant to
    # last for the session and no longer. A reboot or logout clears it, and a
    # fresh daemon forgets it on purpose.
    return os.path.join(runtime_dir(), "session.json")


def applications_dir():
    return os.path.join(_xdg("XDG_DATA_HOME", "~/.local/share"), "applications")


def temp_desktop_file():
    return os.path.join(applications_dir(), f"{APP_ID}.desktop")


def runtime_dir():
    return os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/txtpicker-{os.getuid()}"


def lock_file():
    return os.path.join(runtime_dir(), "txtpicker.lock")


# ── config ──────────────────────────────────────────────────────────────────

def ensure_config():
    if not os.path.exists(config_file()):
        os.makedirs(config_dir(), exist_ok=True)
        with open(config_file(), "w") as f:
            f.write(CONFIG_TEMPLATE)


def read_config():
    """The config file as a dict, created from the template when missing.

    `key = value`, `#` comments, surrounding whitespace stripped, and the first
    value for a key wins.
    """
    ensure_config()
    config = dict(DEFAULTS)
    seen = set()
    with open(config_file()) as f:
        for line in f:
            if line.lstrip().startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if separator and key and value and key not in seen:
                seen.add(key)
                config[key] = value
                if key not in DEFAULTS and not key.lower().startswith("key."):
                    log(f"unknown setting in the config file: {key}")
    return config


# ── snippets ────────────────────────────────────────────────────────────────

def ensure_snippets_file():
    if not os.path.isfile(snippets_file()):
        os.makedirs(os.path.dirname(snippets_file()), exist_ok=True)
        with open(snippets_file(), "w") as f:
            f.write(SNIPPETS_TEMPLATE)


def parse_snippets(lines):
    r"""[(label, text)] from snippet-file lines.

    Blank lines and lines starting with '#' are dropped, "label :: text" splits
    on the first separator, and \n and \t in the text become a newline and a tab.
    """
    snippets = []
    for line in lines:
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        label, separator, text = line.partition(" :: ")
        if not separator:
            label, text = "", line
        snippets.append((label, text.replace("\\n", "\n").replace("\\t", "\t")))
    return snippets


def load_snippets():
    ensure_snippets_file()
    with open(snippets_file()) as f:
        snippets = parse_snippets(f)
    if not snippets:
        die(f"no snippets in {snippets_file()}")
    return snippets


# ── clipboard and pasting ───────────────────────────────────────────────────

def copy_argv():
    if os.environ.get("WAYLAND_DISPLAY"):
        return ["wl-copy"]
    return ["xclip", "-selection", "clipboard"]


def copy(text):
    try:
        subprocess.run(copy_argv(), input=text, text=True, env=child_env(), check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        die(f"could not copy to the clipboard: {error}")


def paste_options(config):
    """The paste keystrokes to cycle through; "auto" picks by window class."""
    options = [option.strip() for option in config["paste"].split(",") if option.strip()]
    return options or [AUTO]


# wtype's modifier names; -M presses, -m releases.
WTYPE_MODIFIERS = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "altgr": "altgr",
                   "shift": "shift", "super": "logo", "win": "logo", "logo": "logo"}


# xdotool's modifier names, for XWayland windows.
XDOTOOL_MODIFIERS = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
                     "altgr": "ISO_Level3_Shift", "super": "super", "win": "super",
                     "logo": "super"}


def split_keystroke(keystroke, modifiers):
    """("Ctrl+Shift+V", table) -> (["ctrl", "shift"], "v") in the table's spelling."""
    mods, key = split_shortcut(keystroke)
    names = []
    for mod in mods:
        if mod not in modifiers:
            raise ValueError(f"unknown modifier in paste keystroke: {mod!r}")
        names.append(modifiers[mod])
    if not key:
        raise ValueError(f"no key in paste keystroke: {keystroke!r}")
    # a single letter is a keysym name, and shift is a modifier of its own: V -> v
    return names, key.lower() if len(key) == 1 else key


def wtype_argv(keystroke):
    """wtype arguments for e.g. "Ctrl+Shift+V": -M presses, -m releases."""
    names, key = split_keystroke(keystroke, WTYPE_MODIFIERS)
    argv = ["wtype"]
    for name in names:
        argv += ["-M", name]
    argv += ["-k", key]
    for name in reversed(names):
        argv += ["-m", name]
    return argv


def xdotool_argv(keystroke):
    """xdotool arguments for e.g. "Ctrl+Y". --clearmodifiers drops anything still
    held down from the shortcut that opened the menu."""
    names, key = split_keystroke(keystroke, XDOTOOL_MODIFIERS)
    return ["xdotool", "key", "--clearmodifiers", "+".join(names + [key])]


# evdev keycodes, taken from linux/input-event-codes.h. The RemoteDesktop
# portal — the only way to synthesize input on GNOME and KDE — presses keycodes,
# not keysyms, so the same keystroke needs a second table over there.
EVDEV_MODIFIERS = {"ctrl": 29, "control": 29, "shift": 42, "alt": 56,
                   "altgr": 100, "super": 125, "win": 125, "logo": 125}
EVDEV_KEYS = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34, "h": 35,
    "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "p": 25,
    "q": 16, "r": 19, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
    "y": 21, "z": 44,
    "0": 11, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9,
    "9": 10,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64, "f7": 65,
    "f8": 66, "f9": 67, "f10": 68, "f11": 87, "f12": 88,
    "escape": 1, "tab": 15, "return": 28, "enter": 28, "kp_enter": 96,
    "space": 57, "backspace": 14, "insert": 110, "delete": 111, "home": 102,
    "end": 107, "page_up": 104, "page_down": 109, "left": 105, "right": 106,
    "up": 103, "down": 108, "minus": 12, "equal": 13, "comma": 51,
    "period": 52, "slash": 53, "semicolon": 39, "apostrophe": 40,
}


def evdev_sequence(keystroke):
    """[(keycode, pressed)] for e.g. "Ctrl+Shift+V", for the RemoteDesktop portal."""
    names, key = split_keystroke(keystroke, EVDEV_MODIFIERS)
    if key.lower() not in EVDEV_KEYS:
        raise ValueError(f"the desktop portal cannot press {key!r}")
    code = EVDEV_KEYS[key.lower()]
    return ([(modifier, 1) for modifier in names]
            + [(code, 1), (code, 0)]
            + [(modifier, 0) for modifier in reversed(names)])


def paste_argv(keystroke, xwayland=False):
    """How to send the keystroke, depending on what the focused window speaks.

    wtype uses the Wayland virtual-keyboard protocol, which hands the compositor
    a temporary keymap. XWayland ignores per-device keymaps, so the keycode
    arrives and is read through the ordinary X keymap — landing on Escape, which
    is why emacs reports `C-<escape>`. For those windows xdotool is the right
    tool: it goes through the X server's XTEST extension, which is exactly what
    XWayland clients listen to.
    """
    return xdotool_argv(keystroke) if xwayland else wtype_argv(keystroke)


TERMINALS = (
    "kitty", "foot", "footclient", "alacritty", "wezterm", "ghostty", "konsole",
    "xterm", "org.wezfurlong.wezterm", "com.mitchellh.ghostty", "org.gnome.terminal",
    "org.gnome.ptyxis", "ptyxis", "gnome-terminal-server", "terminator", "tilix",
    "st-256color",
)


def is_terminal_class(window_class, extra=""):
    if not window_class:
        return False
    return window_class.lower() in TERMINALS + tuple(extra.lower().split())


def focused_window():
    """The focused window as Hyprland describes it: class, xwayland, title, ...

    An empty dict if it cannot be read, which makes every caller fall back to
    the plain Wayland Ctrl+V.
    """
    try:
        reply = subprocess.run(["hyprctl", "activewindow", "-j"], env=child_env(),
                               capture_output=True, text=True, check=False)
        window = json.loads(reply.stdout)
    except (OSError, ValueError):
        return {}
    return window if isinstance(window, dict) else {}


def auto_keystroke(window):
    """What "auto" means: terminals paste with Ctrl+Shift+V, everything else Ctrl+V."""
    window_class = window.get("class") or ""
    if is_terminal_class(window_class, os.environ.get("TXTPICKER_TERMINALS", "")):
        return "Ctrl+Shift+V"
    return FALLBACK_PASTE


def hyprland_paste(keystroke):
    window = focused_window()
    xwayland = bool(window.get("xwayland"))
    if keystroke == AUTO:
        keystroke = auto_keystroke(window)
    try:
        argv = paste_argv(keystroke, xwayland)
    except ValueError as error:
        log(f"{error}; pasting with {FALLBACK_PASTE}")
        argv = paste_argv(FALLBACK_PASTE, xwayland)
    try:
        subprocess.run(argv, env=child_env(), check=False)
    except OSError as error:
        log(f"could not paste ({error}); the snippet is on the clipboard")


# ── the picker window ───────────────────────────────────────────────────────

WIDTH, LIST_HEIGHT = 560, 340

CSS = """
window.txtpicker { background: transparent; }
.panel {
  background: #1f2026;
  color: #e8e8ec;
  border: 1px solid #3b3d46;
  border-radius: 14px;
  padding: 10px;
}
.search-box {
  background: #2a2c33;
  color: #e8e8ec;
  border: 1px solid #3b3d46;
  border-radius: 9px;
  padding: 6px 10px;
  min-height: 30px;
  font-size: 1.1em;
}
.search-box:focus-within { border-color: #5b8def; }
list.snippets { background: transparent; }
list.snippets row {
  padding: 7px 10px;
  border-radius: 8px;
  color: #e8e8ec;
}
list.snippets row:selected { background: #3b6fd9; color: #ffffff; }
list.snippets row:hover:not(:selected) { background: #2c2e36; }
list.snippets row .row-text { color: #8d8f99; font-size: 0.85em; }
list.snippets row:selected .row-text { color: #dce4f7; }
.empty { color: #8d8f99; padding: 14px; }
.hint { color: #8d8f99; font-size: 0.85em; padding: 6px 4px 0 4px; }
.status { color: #e5a3a3; font-size: 0.85em; padding: 2px 4px 0 4px; }
"""


def load_gtk():
    """Import GTK on demand: only the menu needs it, and it is not free."""
    global Gdk, Gio, Gtk, Pango, LayerShell
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LayerShell
    except (ValueError, ImportError):
        LayerShell = None
    from gi.repository import Gdk, Gio, Gtk, Pango


def preview(text):
    """One-line form of a snippet: newlines as ⏎, tabs as spaces."""
    return text.replace("\n", " ⏎ ").replace("\t", " ")


def forward_word_position(text, position):
    """Where emacs's M-f lands: past the end of the next word."""
    index = position
    while index < len(text) and not text[index].isalnum():
        index += 1
    while index < len(text) and text[index].isalnum():
        index += 1
    return index


def backward_word_position(text, position):
    """Where emacs's M-b lands: at the start of the previous word."""
    index = min(position, len(text))
    while index > 0 and not text[index - 1].isalnum():
        index -= 1
    while index > 0 and text[index - 1].isalnum():
        index -= 1
    return index


def wrapped_index(current, step, count):
    """The next row, wrapping around at both ends."""
    return (current + step) % count if count else 0


def clamped_index(current, step, count):
    """The next row, stopping at both ends: what Page Up/Down do."""
    return max(0, min(count - 1, current + step)) if count else 0


def matches(query, label, text, mode):
    """Does this snippet match the query? Case-insensitive substring.

    An empty query matches everything, so an unlabelled snippet is still listed
    in label mode — but as soon as you type, it has nothing to match and drops
    out.
    """
    wanted = query.strip().lower()
    if not wanted:
        return True
    label, text = label.lower(), text.lower()
    if mode == "label":
        return bool(label) and wanted in label
    if mode == "text":
        return wanted in text
    return wanted in label or wanted in text


def resolve_filter(mode):
    """A typo in the config file must not stop the menu from opening."""
    if mode in FILTER_MODES:
        return mode
    log(f"unknown filter {mode!r}; using {DEFAULT_FILTER}")
    return DEFAULT_FILTER


def read_session():
    """What the menu remembers this session: filter, paste keystroke, last pick."""
    try:
        with open(session_file()) as f:
            remembered = json.load(f)
    except (OSError, ValueError):
        return {}
    return remembered if isinstance(remembered, dict) else {}


def write_session(**changes):
    remembered = read_session()
    remembered.update(changes)
    try:
        os.makedirs(runtime_dir(), exist_ok=True)
        with open(session_file(), "w") as f:
            json.dump(remembered, f)  # JSON: a snippet can hold newlines and tabs
    except OSError as error:  # not worth failing a paste over
        log(f"could not remember this session ({error})")


# Each remembered value is stored next to the config value it was chosen against
# (`*_from`), so editing the config file still takes effect instead of being
# silently outvoted by what the menu remembers.

def read_filter(config):
    """The filter to open in: the one last picked with, unless the config changed."""
    remembered = read_session()
    if (remembered.get("filter") in FILTER_MODES
            and remembered.get("filter_from") == config["filter"]):
        return remembered["filter"]
    return resolve_filter(config["filter"])


def save_filter(mode, config):
    write_session(filter=mode, filter_from=config["filter"])


def resolve_mode(mode):
    """A typo in the config file must not stop the menu from opening."""
    if mode in MODES:
        return mode
    log(f"unknown mode {mode!r}; using {DEFAULT_MODE}")
    return DEFAULT_MODE


def read_mode(config):
    """The key mode to open in: the one last picked with, unless the config changed."""
    remembered = read_session()
    if (remembered.get("mode") in MODES
            and remembered.get("mode_from") == config["mode"]):
        return remembered["mode"]
    return resolve_mode(config["mode"])


def save_mode(mode, config):
    write_session(mode=mode, mode_from=config["mode"])


def read_paste(config):
    """The paste keystroke to open with: the one last picked with, else the first."""
    options = paste_options(config)
    remembered = read_session()
    if (remembered.get("paste") in options
            and remembered.get("paste_from") == config["paste"]):
        return remembered["paste"]
    return options[0]


def save_paste(keystroke, config):
    write_session(paste=keystroke, paste_from=config["paste"])


def read_last_chosen():
    text = read_session().get("last")
    return text if isinstance(text, str) else None


def save_last_chosen(text):
    write_session(last=text)


def most_recent_first(snippets, last):
    """The snippet picked last moves to the top; the rest keep file order.

    Matched on the text, not a position, so editing the snippet file cannot
    promote the wrong line.
    """
    if last is None:
        return snippets
    hoisted = [s for s in snippets if s[1] == last]
    if not hoisted:
        return snippets  # it was edited away
    return hoisted + [s for s in snippets if s[1] != last]


def forget_session():
    """Start from the config file again: called when a daemon starts."""
    try:
        os.remove(session_file())
    except OSError:
        pass


# Modifier names as spelled in the config file. Looked up on Gdk by name so this
# table can exist before GTK is imported.
MODIFIER_NAMES = {
    "ctrl": "CONTROL_MASK", "control": "CONTROL_MASK",
    "alt": "ALT_MASK", "mod1": "ALT_MASK",
    "shift": "SHIFT_MASK",
    "super": "SUPER_MASK", "win": "SUPER_MASK", "logo": "SUPER_MASK",
}


def modifier_mask():
    return (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
            | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.SUPER_MASK)


def parse_key(spec):
    """"Ctrl+F" -> (keyval, modifier mask). Raises ValueError on anything unknown."""
    parts = [part for part in spec.replace(" ", "").split("+") if part]
    if not parts:
        raise ValueError(f"empty key: {spec!r}")
    modifiers = 0
    for name in parts[:-1]:
        if name.lower() not in MODIFIER_NAMES:
            raise ValueError(f"unknown modifier: {name!r}")
        modifiers |= getattr(Gdk.ModifierType, MODIFIER_NAMES[name.lower()])
    # Keysym names are case-sensitive ("Down", but "space"), so accept either
    # spelling in the config file.
    for name in (parts[-1], parts[-1].lower()):
        keyval = Gdk.keyval_from_name(name)
        if keyval not in (0, Gdk.KEY_VoidSymbol):  # unknown gives VoidSymbol, not 0
            return keyval, modifiers
    raise ValueError(f"unknown key: {parts[-1]!r}")


def key_specs(config, mode):
    """{action: "Key, Key"} for `mode`, with any key.<action> lines layered on top."""
    specs = dict(EMACS_KEYS if mode == "emacs" else NORMAL_KEYS)
    for name, value in config.items():
        if not name.lower().startswith("key."):
            continue
        action = name[len("key."):].lower()
        if action not in ACTIONS:
            log(f"unknown action in config: key.{action}")
            continue
        specs[action] = value
    return specs


def key_bindings(config, mode):
    """{action: [(keyval, modifiers), ...]} for `mode`.

    A binding that cannot be parsed is dropped with a warning rather than
    breaking the menu, and a key claimed by two actions goes to whichever comes
    first in ACTIONS.
    """
    specs = key_specs(config, mode)
    bindings = {}
    claimed = {}
    for action in ACTIONS:
        for spec in (part.strip() for part in specs.get(action, "").split(",")):
            if not spec:
                continue
            try:
                binding = parse_key(spec)
            except ValueError as error:
                log(f"{error} in key.{action}")
                continue
            owner = claimed.get(binding)
            if owner is not None:
                log(f"{spec} is bound to both {owner} and {action}; using {owner}")
                continue
            claimed[binding] = action
            bindings.setdefault(action, []).append(binding)
    return bindings


class Picker:
    """The picker window, identical on every desktop.

    Hyprland and other layer-shell desktops: a floating overlay that grabs the
    keyboard (gtk4-layer-shell). GNOME: the same window as a small popup.
    Keys: type to filter, Up/Down to move, Enter to pick, Esc to cancel.
    """

    def __init__(self, snippets, settings):
        """settings: config, filter, paste, paste_options, keys.

        An empty paste_options hides the paste hint and disables its key.
        """
        self.snippets = snippets
        self.config = settings["config"]
        self.filter = settings["filter"]
        self.paste_options = settings["paste_options"]
        self.paste = settings["paste"]
        self.keys = settings["keys"]
        self._bindings = {}
        self._specs = {}
        self.mark = None  # emacs mode: set by set_mark, movement then selects
        self.chosen = None
        self.win = None
        self.finishing = False
        self.rows = []
        self.index_of = {}  # row -> position in self.snippets
        self.app = Gtk.Application(application_id=APP_ID,
                                   flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.app.connect("activate", self.build)

    def run(self):
        """Show the window; returns the chosen snippet's text, or None."""
        self.app.run([])
        self.release()
        return self.chosen

    def release(self):
        """Tear the overlay down and make sure the compositor knows.

        The layer surface holds an exclusive keyboard grab, so pressing Ctrl+V
        while it is alive pastes into the overlay instead of the window
        underneath. When the window was its own process this came free: exiting
        closed the Wayland connection. In-process we have to do it, and flush,
        because the main loop is no longer running to push the request out.

        Guarded against re-entry: off Hyprland the window is an ordinary one, so
        destroying it makes it inactive, which fires notify::is-active, which
        calls cancel() — back into here, and over the top of the snippet that
        had just been chosen.
        """
        if self.finishing:
            return
        self.finishing = True
        win, self.win = self.win, None
        if win is not None:
            win.destroy()
        display = Gdk.Display.get_default()
        if display is not None:
            display.flush()

    # ── window ──────────────────────────────────────────────────────────────
    def build(self, app):
        provider = Gtk.CssProvider()
        if hasattr(provider, "load_from_string"):  # GTK >= 4.12
            provider.load_from_string(CSS)
        else:
            provider.load_from_data(CSS.encode(), -1)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        win = self.win = Gtk.ApplicationWindow(application=app, title="txtpicker")
        win.add_css_class("txtpicker")
        win.set_decorated(False)
        win.set_resizable(False)  # a fixed size also makes tiling desktops float it

        self.layer = bool(LayerShell and LayerShell.is_supported())
        if self.layer:
            LayerShell.init_for_window(win)
            LayerShell.set_namespace(win, "txtpicker")
            LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
            LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.EXCLUSIVE)
            # no anchors: the compositor centers the overlay

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.add_css_class("panel")
        panel.set_size_request(WIDTH, -1)

        self.entry = Gtk.SearchEntry(placeholder_text="Search snippets…")
        if hasattr(self.entry, "set_search_delay"):  # GTK >= 4.8
            self.entry.set_search_delay(0)  # it holds each keystroke 150ms otherwise
        self.entry.add_css_class("search-box")
        self.entry.connect("search-changed", self.on_search)
        self.entry.connect("activate", lambda *_: self.choose_selected())
        self.entry.connect("stop-search", lambda *_: self.cancel())
        panel.append(self.entry)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("snippets")
        self.list.set_activate_on_single_click(True)
        self.list.set_filter_func(self.filter_row)
        self.list.connect("row-activated", lambda _l, row: self.choose(row))
        empty = Gtk.Label(label="No matching snippets")
        empty.add_css_class("empty")
        self.list.set_placeholder(empty)
        for index, snippet in enumerate(self.snippets):
            row = self.build_row(snippet)
            self.index_of[row] = index  # filtering must not scan the list per row
            self.rows.append(row)
            self.list.append(row)

        scroll = self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(LIST_HEIGHT)
        scroll.set_child(self.list)
        panel.append(scroll)

        hint = self.hint = Gtk.Label(label=self.hint_text(), xalign=0, wrap=True)
        hint.add_css_class("hint")
        panel.append(hint)

        status = self.status = Gtk.Label(xalign=0, wrap=True)
        status.add_css_class("status")
        panel.append(status)
        self.show_status()

        win.set_child(panel)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

        if not self.layer:
            # A normal window (GNOME): close when the user clicks elsewhere.
            win.connect("notify::is-active", self.on_active_changed)
            self.was_active = False

        self.select_first_visible()
        win.present()
        self.entry.grab_focus()

    def build_row(self, snippet):
        """Label on top, a one-line preview of the text below.

        A snippet with no label keeps a single line, showing just the text.
        """
        label, text = snippet
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        if label:
            top = Gtk.Label(label=label, xalign=0, ellipsize=Pango.EllipsizeMode.END)
            top.add_css_class("row-label")
            box.append(top)
            bottom = Gtk.Label(label=preview(text), xalign=0,
                               ellipsize=Pango.EllipsizeMode.END)
            bottom.add_css_class("row-text")
            box.append(bottom)
        else:
            only = Gtk.Label(label=preview(text), xalign=0,
                             ellipsize=Pango.EllipsizeMode.END)
            only.add_css_class("row-label")
            box.append(only)
        row = Gtk.ListBoxRow(child=box)
        row.set_tooltip_text(text)
        return row

    # ── behaviour ───────────────────────────────────────────────────────────
    # ── bindings ────────────────────────────────────────────────────────────
    def specs(self):
        if self.keys not in self._specs:
            self._specs[self.keys] = key_specs(self.config, self.keys)
        return self._specs[self.keys]

    def bindings(self):
        # Cached per mode, so switching back and forth does not re-warn about a
        # binding the config got wrong.
        if self.keys not in self._bindings:
            self._bindings[self.keys] = key_bindings(self.config, self.keys)
        return self._bindings[self.keys]

    def key_label(self, action):
        """The first key bound to an action, for the hint line."""
        return self.specs().get(action, "").split(",")[0].strip()

    # ── the hint and status lines ───────────────────────────────────────────
    def hint_text(self):
        parts = [f"{self.key_label('cycle_filter')}: {MODE_NAMES[self.filter]}"]
        if self.paste_options:
            parts.append(f"{self.key_label('cycle_paste')}: paste {self.paste}")
        parts.append(f"{self.key_label('cycle_mode')}: {self.keys} keys")
        # Only what can be switched: arrows, Enter and Esc need no introduction.
        return " · ".join(parts)

    def show_status(self, note=None):
        """The line under the hint: a transient note, else anything logged."""
        text = note if note is not None else "\n".join(MESSAGES[-2:])
        self.status.set_text(text)
        self.status.set_visible(bool(text))

    def refresh(self):
        self.hint.set_text(self.hint_text())

    # Each cycle is remembered as it happens, not when a snippet is picked:
    # cancelling the menu should not undo a switch you made deliberately.
    def cycle_filter(self):
        self.filter = FILTER_MODES[(FILTER_MODES.index(self.filter) + 1) % len(FILTER_MODES)]
        save_filter(self.filter, self.config)
        self.refresh()
        self.list.invalidate_filter()
        self.select_first_visible()

    def cycle_paste(self):
        options = self.paste_options
        if not options:
            return
        current = options.index(self.paste) if self.paste in options else -1
        self.paste = options[(current + 1) % len(options)]
        save_paste(self.paste, self.config)
        self.refresh()

    def cycle_mode(self):
        self.keys = MODES[(MODES.index(self.keys) + 1) % len(MODES)]
        save_mode(self.keys, self.config)
        self.mark = None
        self.refresh()
        self.show_status()

    def filter_row(self, row):
        label, text = self.snippets[self.index_of[row]]
        return matches(self.entry.get_text(), label, text, self.filter)

    # ── the search field: emacs-style editing when the mode is on ───────────
    def text(self):
        return self.entry.get_text()

    def cursor(self):
        return self.entry.get_position()

    def go(self, position):
        """Move the cursor, extending the selection while the mark is set."""
        position = max(0, min(len(self.text()), position))
        if self.mark is None:
            self.entry.set_position(position)
        else:
            self.entry.select_region(self.mark, position)

    def toggle_mark(self):
        if self.mark is None:
            self.mark = self.cursor()
            self.show_status("mark set")
        else:
            self.mark = None
            self.entry.select_region(self.cursor(), self.cursor())
            self.show_status("mark cleared")

    def selection(self):
        bounds = self.entry.get_selection_bounds()
        if bounds and bounds[0] and bounds[1] != bounds[2]:
            return bounds[1], bounds[2]
        return None

    def kill_to_end(self):
        self.entry.delete_text(self.cursor(), -1)
        self.mark = None

    def kill_region(self):
        """Cut the selection, or delete the word before the cursor when there is none."""
        region = self.selection()
        if region is None:
            end = self.cursor()
            region = (backward_word_position(self.text(), end), end)
        start, end = region
        if start != end:
            self.entry.delete_text(start, end)
        self.mark = None

    def on_quit(self):
        """Ctrl+G and Esc: drop the mark first, as emacs does, then close."""
        if self.mark is not None:
            self.toggle_mark()
            return
        self.cancel()

    def visible_rows(self):
        return [r for r in self.rows if r.get_child_visible()]

    def select_first_visible(self):
        visible = self.visible_rows()
        if visible:
            self.list.select_row(visible[0])
        else:
            self.list.unselect_all()

    def on_search(self, _entry):
        self.list.invalidate_filter()
        self.select_first_visible()

    def move(self, step, wrap=True):
        visible = self.visible_rows()
        if not visible:
            return
        current = self.list.get_selected_row()
        if current not in visible:
            row = visible[0] if step > 0 else visible[-1]
        else:
            index = (wrapped_index if wrap else clamped_index)(
                visible.index(current), step, len(visible))
            row = visible[index]
        self.list.select_row(row)
        # scroll the row into view; keyboard focus stays in the search box
        ok, rect = row.compute_bounds(self.list)
        if ok:
            self.scroll.get_vadjustment().clamp_page(rect.get_y(),
                                                     rect.get_y() + rect.get_height())

    # ── keys ────────────────────────────────────────────────────────────────
    def action_for(self, keyval, state):
        """Which action this keypress is bound to in the current mode, if any."""
        pressed = (Gdk.keyval_to_lower(keyval), state & modifier_mask())
        bindings = self.bindings()
        for action in ACTIONS:
            for keyval_wanted, modifiers in bindings.get(action, ()):
                if pressed == (Gdk.keyval_to_lower(keyval_wanted), modifiers):
                    return action
        return None

    def handlers(self):
        return {
            "cycle_filter": self.cycle_filter,
            "cycle_paste": self.cycle_paste,
            "cycle_mode": self.cycle_mode,
            "quit": self.on_quit,
            "accept": self.choose_selected,
            "next": lambda: self.move(1),
            "previous": lambda: self.move(-1),
            "page_down": lambda: self.move(8, wrap=False),
            "page_up": lambda: self.move(-8, wrap=False),
            "set_mark": self.toggle_mark,
            "kill_region": self.kill_region,
            "kill_to_end": self.kill_to_end,
            "beginning": lambda: self.go(0),
            "end": lambda: self.go(len(self.text())),
            "forward_char": lambda: self.go(self.cursor() + 1),
            "backward_char": lambda: self.go(self.cursor() - 1),
            "forward_word": lambda: self.go(
                forward_word_position(self.text(), self.cursor())),
            "backward_word": lambda: self.go(
                backward_word_position(self.text(), self.cursor())),
        }

    def on_key(self, _ctrl, keyval, _code, state):
        action = self.action_for(keyval, state)
        handler = self.handlers().get(action)
        if handler is None:
            return False  # anything unbound stays GTK's to deal with
        handler()
        return True

    def on_active_changed(self, win, _param):
        if self.finishing:
            return  # we are the ones who just took the focus away
        if win.is_active():
            self.was_active = True
        elif self.was_active:
            self.cancel()

    def choose_selected(self):
        row = self.list.get_selected_row()
        if row is not None and row.get_child_visible():
            self.choose(row)

    # Destroying the last window ends app.run() on its own. Calling app.quit()
    # as well makes GtkApplication remove a window it has already dropped:
    # "g_list_store_remove: assertion '!g_sequence_iter_is_end (it)' failed".
    def choose(self, row):
        self.chosen = self.snippets[self.index_of[row]][1]
        self.release()

    def cancel(self):
        if self.finishing:
            return  # a pick is already on its way out
        self.chosen = None
        self.release()


# ── the shortcut daemon ─────────────────────────────────────────────────────
# Hyprland: adds a runtime-only bind through hyprctl (nothing written to disk),
#           re-adds it after config reloads and removes it on exit.
# GNOME and others: asks for the shortcut through the XDG GlobalShortcuts
#           portal (the desktop confirms it once), and pastes with Ctrl+V
#           through the RemoteDesktop portal (permission asked once).

def split_shortcut(spec):
    parts = spec.replace(" ", "").split("+")
    return [m.lower() for m in parts[:-1]], parts[-1]


def run_hyprland(shortcut):
    mods, key = split_shortcut(shortcut)
    names = ["CTRL" if m in ("ctrl", "control") else m.upper() for m in mods]
    command = f"{self_path()} menu"

    def hyprctl(*args):
        try:
            r = subprocess.run(["hyprctl", *args], env=child_env(),
                               capture_output=True, text=True)
        except FileNotFoundError:
            sys.exit("txtpicker: hyprctl not found in PATH")
        return (r.stdout + r.stderr).strip() or str(r.returncode)

    # Lua config (newer Hyprland): bind through `hyprctl eval`. The bind object
    # is kept in a Lua global so it can be switched off again later.
    lua_keys = json.dumps(" + ".join(names + [key]))
    lua_bind = ("if txtpicker_bind then pcall(function() txtpicker_bind:set_enabled(false) end) end "
                f"txtpicker_bind = hl.bind({lua_keys}, hl.dsp.exec_cmd({json.dumps(command)}))")
    lua_unbind = ("if txtpicker_bind then txtpicker_bind:set_enabled(false) "
                  "txtpicker_bind = nil end")
    # Classic config (older Hyprland): bind through `hyprctl keyword`.
    keys = f"{' '.join(names)}, {key}"

    mode = ["keyword"]

    def bind():
        if mode[0] == "keyword":
            reply = hyprctl("keyword", "bind", f"{keys}, exec, {command}")
            if reply == "ok":
                return
            if "eval" not in reply:
                log(f"hyprctl keyword bind failed: {reply}")
                return
            mode[0] = "lua"  # "keyword can't work with non-legacy parsers. Use eval."
        reply = hyprctl("eval", lua_bind)
        if reply != "ok":
            log(f"hyprctl eval bind failed: {reply}")

    def unbind():
        if mode[0] == "keyword":
            hyprctl("keyword", "unbind", keys)
        else:
            reply = hyprctl("eval", lua_unbind)
            if reply != "ok":
                log(f"could not remove the bind ({reply}); it stays until Hyprland reloads")

    sock_path = os.path.join(runtime_dir(), "hypr",
                             os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket2.sock")
    events = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    events.connect(sock_path)

    bind()
    log(f"listening for {shortcut} (Hyprland {mode[0]} bind: {' + '.join(names + [key])})")
    try:
        buf = b""
        while True:
            chunk = events.recv(4096)
            if not chunk:  # Hyprland exited
                return
            buf += chunk
            *lines, buf = buf.split(b"\n")
            if any(line.startswith(b"configreloaded>>") for line in lines):
                bind()  # reloads drop runtime binds
    finally:
        unbind()


# Portals only serve apps they can identify. The daemon runs in a systemd scope
# named after the app, and while it runs it also keeps a hidden launcher entry
# in ~/.local/share/applications so it can register its app id. The entry is
# removed when the daemon stops.

created_files = []


def create_temp_desktop_file():
    if os.path.exists(temp_desktop_file()):
        return  # an installed entry already exists; leave it alone
    os.makedirs(applications_dir(), exist_ok=True)
    with open(temp_desktop_file(), "w") as f:
        f.write("[Desktop Entry]\n"
                "Type=Application\n"
                "Name=txtpicker\n"
                "Comment=Temporary entry created by the running txtpicker; removed when it stops\n"
                f"Exec={self_path()}\n"
                "Icon=edit-paste\n"
                "NoDisplay=true\n")
    created_files.append(temp_desktop_file())


def remove_created_files():
    for path in created_files:
        try:
            os.remove(path)
        except OSError:
            pass


def run_portal(shortcut):
    from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
    from jeepney.io.blocking import Proxy, open_dbus_connection

    desktop = "org.freedesktop.portal.Desktop"
    path = "/org/freedesktop/portal/desktop"

    def portal(name):
        return DBusAddress(path, bus_name=desktop, interface=f"org.freedesktop.portal.{name}")

    gs, rd = portal("GlobalShortcuts"), portal("RemoteDesktop")
    reg = DBusAddress(path, bus_name=desktop, interface="org.freedesktop.host.portal.Registry")

    def connect_and_register():
        # Register must be the first portal call on a connection, so each
        # attempt uses a fresh one.
        c = open_dbus_connection(bus="SESSION")
        reply = c.send_and_get_reply(new_method_call(reg, "Register", "sa{sv}", (APP_ID, {})))
        if reply.header.message_type.name == "error":
            c.close()
            return None, str(reply.body)
        return c, None

    create_temp_desktop_file()
    conn, err = connect_and_register()
    for _ in range(20):  # the portal may need a moment to notice the new entry
        if conn is not None or "not found" not in err:
            break
        time.sleep(0.25)
        conn, err = connect_and_register()
    if conn is None:
        log(f"app registration failed ({err}); relying on the systemd scope")
        conn = open_dbus_connection(bus="SESSION")
    bus = Proxy(message_bus, conn)
    sender = conn.unique_name[1:].replace(".", "_")
    counter = [0]

    def call(addr, method, signature, args):
        reply = conn.send_and_get_reply(new_method_call(addr, method, signature, tuple(args)))
        if reply.header.message_type.name == "error":
            raise RuntimeError(f"{method}: {reply.body}")
        return reply.body

    def request(addr, method, signature, args):
        """Call a portal method and wait for its Request::Response signal."""
        counter[0] += 1
        token = f"txtpicker{os.getpid()}_{counter[0]}"
        req_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request",
                         member="Response", path=req_path)
        bus.AddMatch(rule)
        args[-1]["handle_token"] = ("s", token)
        with conn.filter(rule) as queue:
            call(addr, method, signature, args)
            code, results = conn.recv_until_filtered(queue).body
        if code != 0:
            raise RuntimeError(f"{method} was cancelled or denied")
        return {k: v[1] for k, v in results.items()}

    def new_session(addr):
        counter[0] += 1
        return request(addr, "CreateSession", "a{sv}", [
            {"session_handle_token": ("s", f"txtpicker{os.getpid()}s{counter[0]}")}
        ])["session_handle"]

    def close_session(handle):
        try:
            call(DBusAddress(handle, bus_name=desktop, interface="org.freedesktop.portal.Session"),
                 "Close", "", [])
        except RuntimeError:
            pass

    # ── auto-paste: press Ctrl+V through the RemoteDesktop portal ──
    # GNOME asks for permission the first time; the answer is saved as a
    # restore token so later pastes don't ask. If the desktop does not hand
    # out tokens, the session is kept open so it asks at most once per run.
    paste_session = [None]
    paste_enabled = [os.environ.get("TXTPICKER_AUTOPASTE", "1") == "1"]

    def open_paste_session():
        session = new_session(rd)
        select = {"types": ("u", 1), "persist_mode": ("u", 2)}  # keyboard, until revoked
        try:
            with open(token_file()) as f:
                select["restore_token"] = ("s", f.read().strip())
        except OSError:
            pass
        request(rd, "SelectDevices", "oa{sv}", [session, select])
        started = request(rd, "Start", "osa{sv}", [session, "", {}])
        token = started.get("restore_token")
        if token:
            os.makedirs(state_dir(), exist_ok=True)
            with open(token_file(), "w") as f:
                f.write(token)
        return session, bool(token)

    def press(session, sequence):
        for code, state in sequence:
            call(rd, "NotifyKeyboardKeycode", "oa{sv}iu", [session, {}, code, state])
            time.sleep(0.01)

    def paste_sequence():
        """The keycodes for whatever the menu is set to paste with.

        "auto" is plain Ctrl+V here: no portal tells us which app is focused, so
        there is no terminal to detect.
        """
        keystroke = read_paste(read_config())
        if keystroke == AUTO:
            keystroke = FALLBACK_PASTE
        try:
            return evdev_sequence(keystroke)
        except ValueError as error:
            log(f"{error}; pasting with {FALLBACK_PASTE}")
            return evdev_sequence(FALLBACK_PASTE)

    def paste():
        if not paste_enabled[0]:
            return
        sequence = paste_sequence()
        for attempt in (1, 2):
            reused = paste_session[0] is not None
            try:
                if reused:
                    session = paste_session[0]
                else:
                    session, restorable = open_paste_session()
                    time.sleep(0.15)  # let focus settle if a dialog was shown
                press(session, sequence)
                if not reused:
                    if restorable:
                        close_session(session)  # next paste restores silently
                    else:
                        paste_session[0] = session
                return
            except RuntimeError as e:
                paste_session[0] = None  # e.g. stopped from the top-bar indicator
                if attempt == 2 or not reused:
                    log(f"auto-paste unavailable ({e}); the snippet is on the clipboard")
                    if "denied" in str(e):
                        paste_enabled[0] = False
                    return

    # ── the shortcut: GlobalShortcuts portal ──
    try:
        session = new_session(gs)
    except RuntimeError as e:
        sys.exit(f"txtpicker: could not create a shortcut session: {e}")

    mods, key = split_shortcut(shortcut)
    names = {"super": "LOGO", "win": "LOGO", "logo": "LOGO", "control": "CTRL"}
    trigger = "+".join([names.get(m, m.upper()) for m in mods] +
                       [key.lower() if len(key) == 1 else key])

    activated = MatchRule(type="signal", interface="org.freedesktop.portal.GlobalShortcuts",
                          member="Activated", path=path)
    bus.AddMatch(activated)
    with conn.filter(activated, bufsize=64) as queue:
        try:
            bound = request(gs, "BindShortcuts", "oa(sa{sv})sa{sv}", [session, [
                ("open-menu", {"description": ("s", "Open the snippet menu"),
                               "preferred_trigger": ("s", trigger)})], "", {}])
        except RuntimeError as e:
            sys.exit(f"txtpicker: shortcut not registered: {e}")
        for sid, info in bound.get("shortcuts", []):
            desc = info.get("trigger_description", ("s", ""))[1]
            log(f"listening for {sid}: {desc or trigger}")

        while True:
            msg = conn.recv_until_filtered(queue)
            session_handle, shortcut_id, _timestamp, options = msg.body
            if session_handle != session or shortcut_id != "open-menu":
                continue
            env = child_env(TXTPICKER_AUTOPASTE="0")
            token = options.get("activation_token", ("s", None))[1]
            if token:  # lets the menu window take focus
                env["XDG_ACTIVATION_TOKEN"] = token
            if subprocess.run([self_path(), "menu"], env=env).returncode == 0:
                time.sleep(0.2)  # let focus return to the previous window
                paste()
            queue.clear()  # ignore presses made while the menu was open


def daemon_main():
    os.makedirs(runtime_dir(), exist_ok=True)
    forget_session()  # a newly started app starts from the config file
    lock = open(lock_file(), "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("already running")
        return
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()

    # SIGTERM (txtpicker stop/restart, logout) -> clean exit, runs `finally`.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    shortcut = read_config()["shortcut"]
    try:
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            run_hyprland(shortcut)
        else:
            run_portal(shortcut)
    except KeyboardInterrupt:
        pass
    finally:
        remove_created_files()


# ── daemon lifecycle ────────────────────────────────────────────────────────

def pid_from_lock():
    try:
        with open(lock_file()) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def daemon_running():
    """Is another process holding the lock?

    Only call this outside the daemon: the test acquires and releases the lock,
    which in the daemon's own process would drop the lock it is holding.
    """
    if not os.path.exists(lock_file()):
        return False
    try:
        with open(lock_file(), "a+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        return False
    return False


def start_daemon():
    """Detach a daemon, the way `setsid -f` did."""
    subprocess.Popen([self_path(), "daemon"], env=child_env(), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def stop_daemon():
    if not daemon_running():
        return
    pid = pid_from_lock()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(10):
        if not daemon_running():
            return
        time.sleep(0.1)


def scope_argv(program, unit_suffix):
    """Run the daemon in a transient scope named after the app: the XDG portals
    identify apps by their systemd unit name.

    The subcommand has to be passed along — without it the scope would start the
    plain command, which means "start a daemon in the background and exit".
    """
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect",
            "--unit", f"app-{APP_ID}-{unit_suffix}", "--", program, "daemon"]


def run_daemon():
    if (not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
            and not os.environ.get("TXTPICKER_IN_SCOPE")
            and shutil.which("systemd-run")):
        argv = scope_argv(self_path(), f"{os.getpid()}{random.randrange(32768)}")
        os.execvpe(argv[0], argv, child_env(TXTPICKER_IN_SCOPE="1"))
    daemon_main()


# ── command line ────────────────────────────────────────────────────────────

def cmd_menu():
    """Show the menu and copy the chosen snippet. Exit status 1 = cancelled.

    On Hyprland this also presses Ctrl+V; on GNOME the daemon does it once we
    return, which is why it sets TXTPICKER_AUTOPASTE=0 when it starts us.
    """
    snippets = most_recent_first(load_snippets(), read_last_chosen())
    config = read_config()
    hyprland = bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
    settings = {
        "config": config,
        "filter": read_filter(config),
        "paste_options": paste_options(config),
        "paste": read_paste(config),
        "keys": read_mode(config),
    }
    load_gtk()
    picker = Picker(snippets, settings)
    chosen = picker.run()
    if chosen is None:
        sys.exit(1)  # cancelled: nothing copied (the cycles saved themselves)
    save_last_chosen(chosen)
    copy(chosen)
    if hyprland and os.environ.get("TXTPICKER_AUTOPASTE", "1") == "1":
        time.sleep(0.15)  # let focus return to the previous window
        hyprland_paste(picker.paste)


def usage():
    return (
        "usage: txtpicker            start in the background (or open the menu if running)\n"
        "       txtpicker menu       open the menu now\n"
        "       txtpicker stop | restart\n"
        f"       txtpicker edit       edit snippets  ({snippets_file()})\n"
        f"       txtpicker config     edit the shortcut ({config_file()}), then restart\n"
    )


def edit(path):
    editor = os.environ.get("EDITOR") or "xdg-open"
    os.execvpe(editor, [editor, path], child_env())


def main(argv):
    command = argv[1] if len(argv) > 1 else ""
    if command == "":
        # Launched by hand or from the app launcher: start listening for the
        # shortcut if we aren't already, otherwise just show the menu.
        if daemon_running():
            cmd_menu()
        else:
            start_daemon()
            notify("Running in the background until you log out. "
                   "Use your shortcut to open it.")
    elif command == "menu":
        cmd_menu()
    elif command == "daemon":
        run_daemon()
    elif command == "stop":
        stop_daemon()
    elif command == "restart":
        stop_daemon()
        start_daemon()
    elif command == "edit":
        ensure_snippets_file()
        edit(snippets_file())
    elif command == "config":
        ensure_config()
        edit(config_file())
    else:
        sys.stdout.write(usage())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
