"""Fixtures. src/txtpicker.py is imported as a module; it has no import-time side effects."""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import txtpicker  # noqa: E402


@pytest.fixture(scope="session")
def cli():
    return txtpicker


@pytest.fixture(scope="session")
def gtk(cli):
    """Binds the GTK names on the module. Importing needs typelibs, not a display."""
    cli.load_gtk()
    return cli


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """An isolated XDG environment; returns the txtpicker config directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.delenv("TXTPICKER_FILE", raising=False)
    return tmp_path / "config" / "txtpicker"
