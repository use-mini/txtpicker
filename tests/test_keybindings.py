"""Key modes, per-action overrides, and the cursor arithmetic behind them."""


def binding(gtk, spec):
    return gtk.parse_key(spec)


def test_normal_mode_leaves_the_emacs_keys_alone(gtk):
    bindings = gtk.key_bindings({"mode": "normal"}, "normal")
    assert binding(gtk, "Down") in bindings["next"]
    assert binding(gtk, "Escape") in bindings["quit"]
    for action in ("beginning", "kill_to_end", "set_mark", "forward_word"):
        assert action not in bindings  # GTK keeps Ctrl+A, Ctrl+K and friends


def test_emacs_mode_adds_them(gtk):
    bindings = gtk.key_bindings({"mode": "emacs"}, "emacs")
    assert binding(gtk, "Ctrl+N") in bindings["next"]
    assert binding(gtk, "Down") in bindings["next"]  # the plain keys still work
    assert binding(gtk, "Ctrl+G") in bindings["quit"]
    assert bindings["beginning"] == [binding(gtk, "Ctrl+A")]
    assert bindings["set_mark"] == [binding(gtk, "Ctrl+Space")]
    assert bindings["forward_word"] == [binding(gtk, "Alt+F")]


def test_tab_switches_mode_in_both_modes(gtk):
    for mode in gtk.MODES:
        assert gtk.key_bindings({"mode": mode}, mode)["cycle_mode"] == [
            binding(gtk, "Tab")
        ]


def test_the_cycle_keys_do_not_collide_with_emacs(gtk):
    bindings = gtk.key_bindings({"mode": "emacs"}, "emacs")
    assert bindings["cycle_filter"] == [binding(gtk, "Ctrl+Shift+F")]
    assert bindings["cycle_paste"] == [binding(gtk, "Ctrl+Shift+P")]
    assert binding(gtk, "Ctrl+F") in bindings["forward_char"]
    assert binding(gtk, "Ctrl+P") in bindings["previous"]


def test_a_config_line_overrides_the_mode_default(gtk):
    bindings = gtk.key_bindings({"mode": "normal", "key.next": "Ctrl+J"}, "normal")
    assert bindings["next"] == [binding(gtk, "Ctrl+J")]


def test_an_override_applies_in_both_modes(gtk):
    for mode in gtk.MODES:
        bindings = gtk.key_bindings({"mode": mode, "key.quit": "Ctrl+Q"}, mode)
        assert bindings["quit"] == [binding(gtk, "Ctrl+Q")]


def test_an_override_can_add_an_action_the_mode_lacks(gtk):
    bindings = gtk.key_bindings({"mode": "normal", "key.kill_to_end": "Ctrl+K"}, "normal")
    assert bindings["kill_to_end"] == [binding(gtk, "Ctrl+K")]


def test_several_keys_for_one_action(gtk):
    bindings = gtk.key_bindings({"mode": "normal", "key.next": "Down, Ctrl+J, Ctrl+N"},
                                "normal")
    assert len(bindings["next"]) == 3


def test_an_unparseable_binding_is_dropped_with_a_warning(gtk, capsys):
    bindings = gtk.key_bindings({"mode": "normal", "key.next": "Ctrl+Nope, Down"}, "normal")
    assert bindings["next"] == [binding(gtk, "Down")]
    assert "Nope" in capsys.readouterr().err


def test_an_unknown_action_is_reported(gtk, capsys):
    gtk.key_bindings({"mode": "normal", "key.nxet": "Down"}, "normal")
    assert "key.nxet" in capsys.readouterr().err


def test_a_key_bound_twice_goes_to_the_earlier_action(gtk, capsys):
    bindings = gtk.key_bindings(
        {"mode": "normal", "key.next": "Ctrl+J", "key.previous": "Ctrl+J"}, "normal")
    assert bindings["next"] == [binding(gtk, "Ctrl+J")]
    assert "previous" not in bindings
    assert "bound to both" in capsys.readouterr().err


def test_the_mode_falls_back_when_it_is_misspelled(gtk, capsys):
    assert gtk.resolve_mode("emcas") == "normal"
    assert "emcas" in capsys.readouterr().err


# ── the arithmetic the editing keys use ─────────────────────────────────────

def test_forward_word_lands_after_the_next_word(cli):
    assert cli.forward_word_position("hello world", 0) == 5
    assert cli.forward_word_position("hello world", 5) == 11
    assert cli.forward_word_position("hello world", 11) == 11


def test_backward_word_lands_on_the_start_of_the_previous_word(cli):
    assert cli.backward_word_position("hello world", 11) == 6
    assert cli.backward_word_position("hello world", 6) == 0
    assert cli.backward_word_position("hello world", 0) == 0


def test_word_movement_steps_over_punctuation(cli):
    assert cli.forward_word_position("a.b, c", 1) == 3
    assert cli.backward_word_position("a.b, c", 4) == 2


def test_rows_wrap_at_both_ends(cli):
    assert cli.wrapped_index(2, 1, 3) == 0
    assert cli.wrapped_index(0, -1, 3) == 2
    assert cli.wrapped_index(0, 1, 3) == 1
    assert cli.wrapped_index(0, 1, 0) == 0


def test_page_jumps_stop_at_both_ends(cli):
    assert cli.clamped_index(0, -8, 3) == 0
    assert cli.clamped_index(0, 8, 3) == 2
    assert cli.clamped_index(1, 1, 3) == 2


def test_the_mode_is_remembered_for_the_session(cli, config_home):
    config = {"mode": "normal"}
    assert cli.read_mode(config) == "normal"
    cli.save_mode("emacs", config)
    assert cli.read_mode(config) == "emacs"
    assert cli.read_mode({"mode": "emacs"}) == "emacs"  # config edited to match
    cli.forget_session()
    assert cli.read_mode(config) == "normal"
