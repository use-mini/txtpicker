"""The snippet picked last is listed first, for the rest of the session."""

SNIPPETS = [
    ("Signature", "Best regards,\nYour Name"),
    ("", "me@example.com"),
    ("Thanks", "Thanks for your message!"),
]


def test_nothing_remembered_leaves_the_file_order_alone(cli):
    assert cli.most_recent_first(SNIPPETS, None) == SNIPPETS


def test_the_last_chosen_snippet_comes_first(cli):
    assert cli.most_recent_first(SNIPPETS, "Thanks for your message!") == [
        ("Thanks", "Thanks for your message!"),
        ("Signature", "Best regards,\nYour Name"),
        ("", "me@example.com"),
    ]


def test_the_rest_keep_their_file_order(cli):
    reordered = cli.most_recent_first(SNIPPETS, "me@example.com")
    assert reordered[1:] == [SNIPPETS[0], SNIPPETS[2]]


def test_a_snippet_edited_away_is_ignored(cli):
    assert cli.most_recent_first(SNIPPETS, "something deleted") == SNIPPETS


def test_a_multiline_snippet_survives_the_round_trip(cli, config_home):
    cli.save_last_chosen("Best regards,\nYour Name\twith a tab")
    assert cli.read_last_chosen() == "Best regards,\nYour Name\twith a tab"


def test_nothing_saved_reads_as_nothing(cli, config_home):
    assert cli.read_last_chosen() is None


def test_a_junk_session_file_reads_as_nothing(cli, config_home):
    cli.save_last_chosen("x")
    with open(cli.session_file(), "w") as f:
        f.write("{not json")
    assert cli.read_last_chosen() is None


def test_it_is_remembered_in_the_runtime_dir_so_a_reboot_forgets(cli, config_home):
    assert cli.session_file() == cli.runtime_dir() + "/session.json"
