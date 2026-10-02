def test_read_config_creates_the_file_with_defaults(cli, config_home):
    config = cli.read_config()
    assert config["shortcut"] == "Super+Shift+V"
    assert config["filter"] == "both"
    assert config["paste"] == "auto, Ctrl+V, Ctrl+Shift+V"
    assert config["mode"] == "normal"
    assert (config_home / "config").exists()


def test_comments_blank_lines_and_whitespace_are_ignored(cli, config_home):
    config_home.mkdir(parents=True)
    (config_home / "config").write_text("# shortcut = Ctrl+A\n\n  shortcut =  Alt+V  \n")
    assert cli.read_config()["shortcut"] == "Alt+V"


def test_the_first_value_wins(cli, config_home):
    config_home.mkdir(parents=True)
    (config_home / "config").write_text("filter = text\nfilter = label\n")
    assert cli.read_config()["filter"] == "text"


def test_missing_and_empty_keys_fall_back_to_defaults(cli, config_home):
    config_home.mkdir(parents=True)
    (config_home / "config").write_text("shortcut = Alt+V\nfilter =\n")
    config = cli.read_config()
    assert config["filter"] == "both"
    assert config["mode"] == "normal"


def test_paths_follow_the_environment(cli, config_home, monkeypatch):
    assert cli.config_file() == str(config_home / "config")
    assert cli.snippets_file() == str(config_home / "snippets.txt")
    monkeypatch.setenv("TXTPICKER_FILE", "/tmp/elsewhere.txt")
    assert cli.snippets_file() == "/tmp/elsewhere.txt"


def test_the_template_documents_every_key_it_sets(cli):
    for key in cli.DEFAULTS:
        assert f"{key} = " in cli.CONFIG_TEMPLATE


def test_a_setting_we_no_longer_use_is_reported(cli, config_home, capsys):
    config_home.mkdir(parents=True)
    (config_home / "config").write_text("filter_key = Ctrl+F\nkey.next = Down\n")
    cli.read_config()
    errors = capsys.readouterr().err
    assert "filter_key" in errors      # renamed to key.cycle_filter
    assert "key.next" not in errors    # key.* is a valid namespace
