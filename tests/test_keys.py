"""Key parsing. Needs the GTK typelibs for Gdk keyvals, but no display."""
import pytest


def test_ctrl_f_is_the_f_key_with_control(gtk):
    keyval, modifiers = gtk.parse_key("Ctrl+F")
    assert gtk.Gdk.keyval_to_lower(keyval) == gtk.Gdk.keyval_from_name("f")
    assert modifiers == gtk.Gdk.ModifierType.CONTROL_MASK


def test_modifier_names_have_aliases(gtk):
    assert gtk.parse_key("control+f")[1] == gtk.Gdk.ModifierType.CONTROL_MASK
    assert gtk.parse_key("super+f")[1] == gtk.Gdk.ModifierType.SUPER_MASK
    assert gtk.parse_key("win+f")[1] == gtk.Gdk.ModifierType.SUPER_MASK
    assert gtk.parse_key("mod1+f")[1] == gtk.Gdk.ModifierType.ALT_MASK


def test_modifiers_combine(gtk):
    assert gtk.parse_key("Ctrl+Shift+T")[1] == (
        gtk.Gdk.ModifierType.CONTROL_MASK | gtk.Gdk.ModifierType.SHIFT_MASK)


def test_a_key_without_modifiers_is_allowed(gtk):
    keyval, modifiers = gtk.parse_key("F2")
    assert keyval == gtk.Gdk.KEY_F2
    assert modifiers == 0


def test_spaces_are_ignored(gtk):
    assert gtk.parse_key("Ctrl + F") == gtk.parse_key("Ctrl+F")


def test_unknown_keys_and_modifiers_raise(gtk):
    with pytest.raises(ValueError):
        gtk.parse_key("Ctrl+NotAKey")
    with pytest.raises(ValueError):
        gtk.parse_key("Hyper+F")
    with pytest.raises(ValueError):
        gtk.parse_key("")


def test_keysym_names_are_accepted_in_either_case(gtk):
    assert gtk.parse_key("Ctrl+Space") == gtk.parse_key("Ctrl+space")
    assert gtk.parse_key("Page_Down")[0] == gtk.Gdk.KEY_Page_Down
    assert gtk.parse_key("Down")[0] == gtk.Gdk.KEY_Down


def test_the_modifier_mask_covers_every_name_we_accept(gtk):
    mask = gtk.modifier_mask()
    for attribute in set(gtk.MODIFIER_NAMES.values()):
        assert getattr(gtk.Gdk.ModifierType, attribute) & mask
