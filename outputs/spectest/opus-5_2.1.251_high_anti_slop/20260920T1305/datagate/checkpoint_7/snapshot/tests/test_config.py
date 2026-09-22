"""Tests for the configuration sources, their precedence and their validation."""

import pytest

from datagate.app import create_app
from datagate.config import DEFAULT_STORAGE_DIR, ConfigError, load_config


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Return a factory writing a DATAGATE_CONFIG file with the given contents."""

    def write(contents: str) -> None:
        path = tmp_path / "datagate.conf"
        path.write_text(contents, encoding="utf-8")
        monkeypatch.setenv("DATAGATE_CONFIG", str(path))

    return write


def test_defaults_apply_without_any_setting(monkeypatch):
    monkeypatch.delenv("STORAGE_DIR", raising=False)

    config = load_config()

    assert config.max_source_size is None
    assert config.origin_allowlist == ()
    assert config.require_tls is False
    assert config.storage_dir == DEFAULT_STORAGE_DIR
    assert config.cache_enabled is True


def test_config_file_settings_are_read(config_file):
    config_file("MAX_SOURCE_SIZE=2048\nREQUIRE_TLS=yes\nCACHE_ENABLED=off\n")

    config = load_config()

    assert config.max_source_size == 2048
    assert config.require_tls is True
    assert config.cache_enabled is False


def test_environment_overrides_the_config_file(config_file, monkeypatch):
    config_file("MAX_SOURCE_SIZE=2048\n")
    monkeypatch.setenv("MAX_SOURCE_SIZE", "10")

    assert load_config().max_source_size == 10


def test_blank_and_comment_lines_are_ignored(config_file):
    config_file("# a comment\n\n   \nREQUIRE_TLS=on\n")

    assert load_config().require_tls is True


def test_list_values_are_split_on_commas(config_file):
    config_file("ORIGIN_ALLOWLIST=example.com, Data.Example.ORG ,\n")

    assert load_config().origin_allowlist == ("example.com", "data.example.org")


@pytest.mark.parametrize("value", ["1", "TRUE", " yes ", "On"])
def test_booleans_accept_the_documented_spellings(config_file, value):
    config_file(f"REQUIRE_TLS={value}\n")

    assert load_config().require_tls is True


@pytest.mark.parametrize(
    "contents",
    [
        "REQUIRE_TLS=maybe\n",
        "CACHE_ENABLED=\n",
        "MAX_SOURCE_SIZE=lots\n",
        "MAX_SOURCE_SIZE=-1\n",
        "REQUIRE_TLS\n",
        "TIMEOUT=5\n",
    ],
)
def test_invalid_config_fails_startup(config_file, contents):
    config_file(contents)

    with pytest.raises(ConfigError):
        create_app()


def test_unreadable_config_file_fails_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAGATE_CONFIG", str(tmp_path / "absent.conf"))

    with pytest.raises(ConfigError):
        create_app()
