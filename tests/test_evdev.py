"""Keycodes for the RemoteDesktop portal, which is how GNOME and KDE paste.

Values come from linux/input-event-codes.h: KEY_LEFTCTRL 29, KEY_LEFTSHIFT 42,
KEY_V 47, KEY_Y 21, KEY_LEFTMETA 125.
"""
import pytest


def test_ctrl_v_is_what_the_portal_path_sent_before(cli):
    assert cli.evdev_sequence("Ctrl+V") == [(29, 1), (47, 1), (47, 0), (29, 0)]


def test_ctrl_shift_v_releases_in_reverse(cli):
    assert cli.evdev_sequence("Ctrl+Shift+V") == [
        (29, 1), (42, 1), (47, 1), (47, 0), (42, 0), (29, 0)
    ]


def test_emacs_yank(cli):
    assert cli.evdev_sequence("Ctrl+Y") == [(29, 1), (21, 1), (21, 0), (29, 0)]


def test_super_is_the_meta_key(cli):
    assert cli.evdev_sequence("Super+V")[0] == (125, 1)


def test_a_key_on_its_own(cli):
    assert cli.evdev_sequence("F5") == [(63, 1), (63, 0)]


def test_named_keys_and_case(cli):
    assert cli.evdev_sequence("Shift+Insert") == [(42, 1), (110, 1), (110, 0), (42, 0)]
    assert cli.evdev_sequence("ctrl+v") == cli.evdev_sequence("Ctrl+V")


def test_a_key_the_table_lacks_is_rejected(cli):
    with pytest.raises(ValueError, match="cannot press"):
        cli.evdev_sequence("Ctrl+Multi_key")


def test_an_unknown_modifier_is_rejected(cli):
    with pytest.raises(ValueError):
        cli.evdev_sequence("Hyper+V")


def test_every_letter_and_digit_can_be_pressed(cli):
    for key in "abcdefghijklmnopqrstuvwxyz0123456789":
        assert len(cli.evdev_sequence(f"Ctrl+{key}")) == 4


def test_the_three_paste_defaults_all_translate(cli):
    for keystroke in cli.paste_options({"paste": cli.DEFAULT_PASTE}):
        if keystroke != cli.AUTO:
            assert cli.evdev_sequence(keystroke)
