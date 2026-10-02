"""The paste keystroke: the options, the wtype argv, and the session memory."""
import pytest


def test_the_options_come_from_a_comma_separated_list(cli):
    assert cli.paste_options({"paste": "auto, Ctrl+V, Ctrl+Y"}) == ["auto", "Ctrl+V", "Ctrl+Y"]


def test_blank_entries_and_stray_spaces_are_dropped(cli):
    assert cli.paste_options({"paste": " Ctrl+V , , Ctrl+Y ,"}) == ["Ctrl+V", "Ctrl+Y"]


def test_an_empty_setting_still_leaves_auto(cli):
    assert cli.paste_options({"paste": ""}) == ["auto"]


def test_ctrl_v_argv_is_what_the_shell_version_sent(cli):
    assert cli.paste_argv("Ctrl+V") == ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]


def test_ctrl_shift_v_argv_is_what_the_shell_version_sent(cli):
    assert cli.paste_argv("Ctrl+Shift+V") == [
        "wtype", "-M", "ctrl", "-M", "shift", "-k", "v", "-m", "shift", "-m", "ctrl"
    ]


def test_emacs_yank(cli):
    assert cli.paste_argv("Ctrl+Y") == ["wtype", "-M", "ctrl", "-k", "y", "-m", "ctrl"]


def test_super_becomes_logo_for_wtype(cli):
    assert cli.paste_argv("Super+V") == ["wtype", "-M", "logo", "-k", "v", "-m", "logo"]


def test_a_named_key_is_passed_through(cli):
    assert cli.paste_argv("Shift+Insert") == [
        "wtype", "-M", "shift", "-k", "Insert", "-m", "shift"
    ]


def test_a_key_on_its_own_needs_no_modifiers(cli):
    assert cli.paste_argv("F5") == ["wtype", "-k", "F5"]


def test_an_unknown_modifier_is_rejected(cli):
    with pytest.raises(ValueError):
        cli.paste_argv("Hyper+V")
    with pytest.raises(ValueError):
        cli.paste_argv("Hyper+V", xwayland=True)


def test_a_keystroke_with_no_key_is_rejected(cli):
    with pytest.raises(ValueError):
        cli.paste_argv("Ctrl+")


# XWayland windows ignore wtype's keymap, so they are typed into with xdotool.

def test_xwayland_windows_use_xdotool(cli):
    assert cli.paste_argv("Ctrl+Y", xwayland=True) == [
        "xdotool", "key", "--clearmodifiers", "ctrl+y"
    ]


def test_wayland_windows_use_wtype(cli):
    assert cli.paste_argv("Ctrl+Y", xwayland=False)[0] == "wtype"


def test_xdotool_spells_modifiers_its_own_way(cli):
    assert cli.xdotool_argv("Ctrl+Shift+V")[-1] == "ctrl+shift+v"
    assert cli.xdotool_argv("Super+V")[-1] == "super+v"


def test_xdotool_keeps_named_keys(cli):
    assert cli.xdotool_argv("Shift+Insert")[-1] == "shift+Insert"
    assert cli.xdotool_argv("F5")[-1] == "F5"


def test_without_a_session_the_first_option_is_used(cli, config_home):
    assert cli.read_paste({"paste": "auto, Ctrl+Y"}) == "auto"


def test_the_remembered_keystroke_wins(cli, config_home):
    config = {"paste": "auto, Ctrl+Y"}
    cli.save_paste("Ctrl+Y", config)
    assert cli.read_paste(config) == "Ctrl+Y"


def test_editing_the_option_list_overrides_what_was_remembered(cli, config_home):
    cli.save_paste("Ctrl+Y", {"paste": "auto, Ctrl+Y"})
    assert cli.read_paste({"paste": "Ctrl+V, Ctrl+Shift+V"}) == "Ctrl+V"


def test_a_keystroke_no_longer_in_the_list_is_ignored(cli, config_home):
    cli.save_paste("Ctrl+Y", {"paste": "auto, Ctrl+Y"})
    cli.write_session(paste_from="auto")  # same list, but the entry is gone
    assert cli.read_paste({"paste": "auto"}) == "auto"


def test_the_filter_and_the_paste_are_remembered_side_by_side(cli, config_home):
    config = {"filter": "both", "paste": "auto, Ctrl+Y"}
    cli.save_filter("label", config)
    cli.save_paste("Ctrl+Y", config)
    cli.save_last_chosen("me@example.com")
    assert cli.read_filter(config) == "label"
    assert cli.read_paste(config) == "Ctrl+Y"
    assert cli.read_last_chosen() == "me@example.com"


def test_a_fresh_daemon_forgets_all_of_it(cli, config_home):
    config = {"filter": "both", "paste": "auto, Ctrl+Y"}
    cli.save_filter("label", config)
    cli.save_paste("Ctrl+Y", config)
    cli.save_last_chosen("me@example.com")
    cli.forget_session()
    assert cli.read_filter(config) == "both"
    assert cli.read_paste(config) == "auto"
    assert cli.read_last_chosen() is None
