def test_split_shortcut_separates_modifiers_from_the_key(cli):
    assert cli.split_shortcut("Super+Shift+V") == (["super", "shift"], "V")
    assert cli.split_shortcut("Ctrl+Alt+space") == (["ctrl", "alt"], "space")
    assert cli.split_shortcut("F2") == ([], "F2")


def test_scope_argv_names_the_unit_after_the_app(cli):
    argv = cli.scope_argv("/nix/store/x/bin/txtpicker", "1234")
    assert argv[:2] == ["systemd-run", "--user"]
    assert "--scope" in argv
    assert f"app-{cli.APP_ID}-1234" in argv


def test_the_scope_runs_the_daemon_subcommand(cli):
    """Without the subcommand the scope starts a detached daemon and exits."""
    argv = cli.scope_argv("/nix/store/x/bin/txtpicker", "1234")
    assert argv[-3:] == ["--", "/nix/store/x/bin/txtpicker", "daemon"]


def test_no_lock_file_means_no_daemon(cli, config_home):
    assert cli.pid_from_lock() is None
    assert cli.daemon_running() is False


def test_an_unheld_lock_file_means_no_daemon(cli, config_home, tmp_path):
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    (run / "txtpicker.lock").write_text("4242")
    assert cli.daemon_running() is False


def test_the_pid_is_read_from_the_lock_file(cli, config_home, tmp_path):
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    (run / "txtpicker.lock").write_text("4242\n")
    assert cli.pid_from_lock() == 4242


def test_a_junk_lock_file_has_no_pid(cli, config_home, tmp_path):
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    (run / "txtpicker.lock").write_text("not-a-pid")
    assert cli.pid_from_lock() is None


def test_self_path_prefers_the_wrapper_on_path(cli, monkeypatch, tmp_path):
    """Installed, the daemon must start the wrapper, not the script inside it."""
    wrapper = tmp_path / "txtpicker"
    wrapper.write_text("#!/bin/sh\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli.self_path() == str(wrapper)


def test_self_path_falls_back_to_this_file_in_a_checkout(cli, monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert cli.self_path().endswith("src/txtpicker.py")
