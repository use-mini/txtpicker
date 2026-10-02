def test_wayland_copies_with_wl_copy(cli, monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    assert cli.copy_argv() == ["wl-copy"]


def test_x11_copies_with_xclip(cli, monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert cli.copy_argv() == ["xclip", "-selection", "clipboard"]


def test_auto_pastes_with_ctrl_shift_v_in_a_terminal(cli):
    assert cli.auto_keystroke({"class": "kitty"}) == "Ctrl+Shift+V"


def test_auto_pastes_with_ctrl_v_elsewhere(cli):
    assert cli.auto_keystroke({"class": "firefox"}) == "Ctrl+V"


def test_auto_falls_back_to_ctrl_v_when_the_window_is_unknown(cli):
    assert cli.auto_keystroke({}) == "Ctrl+V"
    assert cli.auto_keystroke({"class": None}) == "Ctrl+V"


def test_auto_honours_extra_terminals_from_the_environment(cli, monkeypatch):
    monkeypatch.setenv("TXTPICKER_TERMINALS", "myterm")
    assert cli.auto_keystroke({"class": "myterm"}) == "Ctrl+Shift+V"


def test_known_terminal_classes_match_regardless_of_case(cli):
    assert cli.is_terminal_class("Kitty")
    assert cli.is_terminal_class("com.mitchellh.Ghostty")
    assert cli.is_terminal_class("org.gnome.Ptyxis")


def test_other_classes_are_not_terminals(cli):
    assert not cli.is_terminal_class("firefox")
    assert not cli.is_terminal_class("")


def test_extra_terminal_classes_come_from_the_environment(cli):
    assert cli.is_terminal_class("MyTerm", extra="myterm otherterm")
    assert not cli.is_terminal_class("MyTerm", extra="otherterm")


def test_child_env_drops_the_gtk_wrapping(cli, monkeypatch):
    monkeypatch.setenv("LD_PRELOAD", "/nix/store/x/lib/libgtk4-layer-shell.so")
    monkeypatch.setenv("GI_TYPELIB_PATH", "/nix/store/y/lib/girepository-1.0")
    monkeypatch.setenv("PATH", "/usr/bin")
    environment = cli.child_env()
    assert "LD_PRELOAD" not in environment
    assert "GI_TYPELIB_PATH" not in environment
    assert environment["PATH"] == "/usr/bin"  # how children find us and our helpers


def test_child_env_takes_additions(cli):
    assert cli.child_env(TXTPICKER_AUTOPASTE="0")["TXTPICKER_AUTOPASTE"] == "0"
