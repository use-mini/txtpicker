# txtpicker

Press a shortcut, pick a text snippet from a floating list, and it is pasted into
the window you were working in (and left on the clipboard). Works on Hyprland and
on GNOME/KDE through the XDG desktop portals.

## How it works

One program, [`src/txtpicker.py`](src/txtpicker.py), with subcommands. Two
processes while it runs: the daemon blocks waiting for the shortcut, so it cannot
also run a GTK main loop — when the shortcut fires it starts `txtpicker menu` and
waits for it.

The daemon grabs the shortcut differently per desktop, with no permanent changes
to your system:

- **Hyprland** — a runtime-only `hyprctl` bind, re-added after config reloads and
  removed on exit. Nothing is written to your Hyprland config.
- **GNOME, KDE, …** — the shortcut comes from the `GlobalShortcuts` portal and the
  Ctrl+V keystroke from the `RemoteDesktop` portal, each confirmed once by the
  desktop. While the daemon runs it keeps a hidden launcher entry in
  `~/.local/share/applications` so the portals can identify the app; it is removed
  when the daemon stops.

## Use it

```sh
nix run github:<you>/txtpicker        # start listening in the background
nix profile install github:<you>/txtpicker
```

Or as a flake input:

```nix
inputs.txtpicker.url = "github:<you>/txtpicker";
# then, in your package list:
inputs.txtpicker.packages.${system}.default
```

Commands:

```
txtpicker            start in the background (or open the menu if already running)
txtpicker menu       open the menu now
txtpicker stop | restart
txtpicker edit       edit snippets
txtpicker config     edit the shortcut and the filter, then restart
```

In the menu: type to filter, `↑`/`↓` to move, `Enter` to paste, `Esc` to cancel,
and `Ctrl+F` to change what the filter matches.

## Configuration

`~/.config/txtpicker/snippets.txt` — one snippet per line, created on first run:

```
# blank lines and lines starting with '#' are ignored
my.email@example.com
Signature :: Best regards,\nYour Name
```

`\n` and `\t` become a line break and a tab. `label :: text` shows the label in the
menu with the text beneath it, and copies the text.

`~/.config/txtpicker/config`:

```
# Shortcut that opens the snippet menu, e.g. Super+Shift+V or Ctrl+Alt+space
# After changing it, run: txtpicker restart
shortcut = Super+Shift+V

# What typing in the search box matches: both | label | text
filter = both

# Key that cycles the filter while the menu is open
filter_key = Ctrl+F
```

`shortcut` needs a `txtpicker restart`; `filter` and `filter_key` are read each time
the menu opens. `filter_key` cycles label+text → label → text for the menu you have
open — the starting point is always `filter`, and the menu never writes to this file.
A value it cannot make sense of is reported on stderr and the default used, so a typo
here never stops the menu from opening.

Environment variables:

| Variable | Effect |
| --- | --- |
| `TXTPICKER_FILE` | use a different snippet file |
| `TXTPICKER_TERMINALS` | extra window classes that paste with Ctrl+Shift+V |
| `TXTPICKER_AUTOPASTE=0` | only copy to the clipboard, never press Ctrl+V |

## Development

```sh
nix develop                                  # Python 3 with jeepney, pygobject3, pytest, GTK 4
python3 -m pytest -q tests                   # 49 tests, no display needed
nix flake check                              # the tests plus the build

printf 'Signature :: Best regards,\\nYour Name\n' > /tmp/snippets.txt
TXTPICKER_FILE=/tmp/snippets.txt LD_PRELOAD=$GTK4_LAYER_SHELL ./src/txtpicker.py menu
```

The script keeps a `#!/usr/bin/env python3` line so it runs from the checkout; the
build rewrites it to the pinned interpreter. It calls its helpers (`wl-copy`,
`xclip`, `wtype`, `notify-send`) by bare name, and finds *itself* the same way —
`wrapGAppsHook4` puts them and `$out/bin` on `PATH`, along with the GTK typelibs and
the `gtk4-layer-shell` preload. That is also why the daemon starts `txtpicker` from
`PATH` rather than `__file__`: inside the wrapper, `__file__` is the unwrapped
script, which would start without any of that environment.

Flake output: `txtpicker` (also `default`) — the command plus the desktop entry.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
