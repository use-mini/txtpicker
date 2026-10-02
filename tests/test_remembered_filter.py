"""The menu remembers the filter it was last used with, in the state dir."""


def test_without_a_state_file_the_config_decides(cli, config_home):
    assert cli.read_filter({"filter": "text"}) == "text"


def test_a_remembered_mode_wins_over_the_config_default(cli, config_home):
    cli.save_filter("label", {"filter": "both"})
    assert cli.read_filter({"filter": "both"}) == "label"


def test_editing_the_config_overrides_what_was_remembered(cli, config_home):
    cli.save_filter("label", {"filter": "both"})
    assert cli.read_filter({"filter": "text"}) == "text"


def test_a_junk_session_file_is_ignored(cli, config_home):
    cli.save_filter("label", {"filter": "both"})
    cli.write_session(filter="lebel")
    assert cli.read_filter({"filter": "both"}) == "both"


def test_an_unreadable_config_value_still_resolves(cli, config_home, capsys):
    assert cli.read_filter({"filter": "nonsense"}) == "both"
    assert "nonsense" in capsys.readouterr().err


def test_it_is_remembered_in_the_runtime_dir_so_a_reboot_forgets(cli, config_home):
    cli.save_filter("text", {"filter": "both"})
    assert cli.session_file() == cli.runtime_dir() + "/session.json"
    assert cli.read_filter({"filter": "both"}) == "text"


def test_a_fresh_daemon_forgets_it(cli, config_home):
    cli.save_filter("label", {"filter": "both"})
    cli.save_last_chosen("me@example.com")
    cli.forget_session()
    assert cli.read_filter({"filter": "both"}) == "both"
    assert cli.read_last_chosen() is None


def test_forgetting_twice_is_not_an_error(cli, config_home):
    cli.forget_session()
    cli.forget_session()
