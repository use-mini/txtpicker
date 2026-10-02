import pytest


def test_label_and_text_split_on_the_first_separator(cli):
    assert cli.parse_snippets(["Signature :: Best regards :: and so on"]) == [
        ("Signature", "Best regards :: and so on")
    ]


def test_unlabelled_lines_have_an_empty_label(cli):
    assert cli.parse_snippets(["me@example.com"]) == [("", "me@example.com")]


def test_blank_whitespace_and_comment_lines_are_skipped(cli):
    assert cli.parse_snippets(["", "   ", "\t", "# a comment", "keep\n"]) == [("", "keep")]


def test_escapes_are_expanded_in_labelled_and_unlabelled_text(cli):
    assert cli.parse_snippets([r"Sig :: a\nb\tc"]) == [("Sig", "a\nb\tc")]
    assert cli.parse_snippets([r"a\nb"]) == [("", "a\nb")]


def test_a_hash_inside_a_line_is_not_a_comment(cli):
    assert cli.parse_snippets(["issue #42"]) == [("", "issue #42")]


def test_load_snippets_creates_the_file_and_reads_the_examples(cli, config_home):
    snippets = cli.load_snippets()
    assert ("Signature", "Best regards,\nYour Name") in snippets
    assert ("", "my.email@example.com") in snippets


def test_load_snippets_dies_when_the_file_has_no_snippets(cli, config_home, monkeypatch, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("# only a comment\n")
    monkeypatch.setenv("TXTPICKER_FILE", str(empty))
    monkeypatch.setattr(cli, "notify", lambda message: None)
    with pytest.raises(SystemExit) as exit_info:
        cli.load_snippets()
    assert exit_info.value.code == 1


def test_the_example_file_parses_into_three_snippets(cli):
    assert len(cli.parse_snippets(cli.SNIPPETS_TEMPLATE.splitlines())) == 3
