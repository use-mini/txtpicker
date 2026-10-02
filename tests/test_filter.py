def test_both_matches_the_label_or_the_text(cli):
    assert cli.matches("sig", "Signature", "Best regards", "both")
    assert cli.matches("regards", "Signature", "Best regards", "both")
    assert not cli.matches("zzz", "Signature", "Best regards", "both")


def test_label_mode_ignores_the_text(cli):
    assert cli.matches("sig", "Signature", "Best regards", "label")
    assert not cli.matches("regards", "Signature", "Best regards", "label")


def test_label_mode_hides_unlabelled_snippets_once_you_type(cli):
    assert not cli.matches("example", "", "me@example.com", "label")


def test_label_mode_still_lists_unlabelled_snippets_with_an_empty_search(cli):
    assert cli.matches("", "", "me@example.com", "label")
    assert cli.matches("  ", "", "me@example.com", "label")


def test_text_mode_ignores_the_label(cli):
    assert cli.matches("regards", "Signature", "Best regards", "text")
    assert not cli.matches("sig", "Signature", "Best regards", "text")


def test_matching_is_case_insensitive_on_both_sides(cli):
    assert cli.matches("SIGNATURE", "signature", "", "both")
    assert cli.matches("signature", "SIGNATURE", "", "label")


def test_an_empty_or_blank_query_matches_everything(cli):
    assert cli.matches("", "", "", "label")
    assert cli.matches("   ", "Signature", "x", "text")


def test_an_unknown_filter_falls_back_to_both(cli, capsys):
    assert cli.resolve_filter("lebel") == "both"
    assert "lebel" in capsys.readouterr().err


def test_a_known_filter_is_kept(cli):
    for mode in cli.FILTER_MODES:
        assert cli.resolve_filter(mode) == mode


def test_every_mode_has_a_display_name(cli):
    assert set(cli.MODE_NAMES) == set(cli.FILTER_MODES)
    assert cli.MODE_NAMES["both"] == "label+text"


def test_preview_puts_newlines_and_tabs_on_one_line(cli):
    assert cli.preview("Best regards,\nYour Name") == "Best regards, ⏎ Your Name"
    assert cli.preview("a\tb") == "a b"
