"""Loading settings from the defaults, the config file and the environment."""

import sys

import pytest

import datagate

from gateway.config import (
    DEFAULT_STORAGE_DIR,
    ConfigurationError,
    Settings,
    load_settings,
)

CONFIG = """
# datagate settings
MAX_SOURCE_SIZE=2048

ORIGIN_ALLOWLIST=example.com, docs.example.org
REQUIRE_TLS=yes
CACHE_ENABLED=off
"""


@pytest.fixture
def config_file(tmp_path):
    """Write ``text`` to a config file and return the environment naming it."""

    def write(text: str) -> dict[str, str]:
        path = tmp_path / "datagate.conf"
        path.write_text(text, encoding="utf-8")
        return {"DATAGATE_CONFIG": str(path)}

    return write


def test_defaults_apply_to_an_empty_environment():
    assert load_settings({}) == Settings(
        max_source_size=None,
        origin_allowlist=(),
        require_tls=False,
        storage_dir=DEFAULT_STORAGE_DIR,
        cache_enabled=True,
    )


def test_config_file_fills_every_setting_it_names(config_file):
    settings = load_settings(config_file(CONFIG))

    assert settings.max_source_size == 2048
    assert settings.origin_allowlist == ("example.com", "docs.example.org")
    assert settings.require_tls is True
    assert settings.cache_enabled is False
    assert settings.storage_dir == DEFAULT_STORAGE_DIR


def test_environment_wins_over_the_config_file(config_file):
    environment = config_file(CONFIG) | {"MAX_SOURCE_SIZE": "10", "REQUIRE_TLS": "no"}
    settings = load_settings(environment)

    assert settings.max_source_size == 10
    assert settings.require_tls is False
    assert settings.cache_enabled is False


def test_leading_dots_and_case_leave_the_allowlist(config_file):
    environment = config_file("ORIGIN_ALLOWLIST=.Example.COM,.org.Example.net")
    assert load_settings(environment).origin_allowlist == (
        "example.com",
        "org.example.net",
    )


@pytest.mark.parametrize("word", ["1", "true", "TRUE", " yes ", "On"])
def test_true_words_are_read_in_any_case_and_spacing(word):
    assert load_settings({"REQUIRE_TLS": word}).require_tls is True


@pytest.mark.parametrize("word", ["0", "false", "FALSE", " no ", "Off"])
def test_false_words_are_read_in_any_case_and_spacing(word):
    assert load_settings({"CACHE_ENABLED": word}).cache_enabled is False


@pytest.mark.parametrize(
    "environment",
    [
        {"REQUIRE_TLS": "maybe"},
        {"CACHE_ENABLED": ""},
        {"MAX_SOURCE_SIZE": "2 kB"},
        {"MAX_SOURCE_SIZE": "-1"},
        {"ORIGIN_ALLOWLIST": "example.com,"},
        {"STORAGE_DIR": "  "},
    ],
)
def test_unreadable_values_are_refused(environment):
    with pytest.raises(ConfigurationError):
        load_settings(environment)


@pytest.mark.parametrize(
    "text", ["MAX_SOURCE_SIZE 2048", "MAX_SIZE=2048", "REQUIRE_TLS=sometimes"]
)
def test_unreadable_config_file_lines_are_refused(config_file, text):
    with pytest.raises(ConfigurationError):
        load_settings(config_file(text))


def test_missing_config_file_is_refused(tmp_path):
    with pytest.raises(ConfigurationError):
        load_settings({"DATAGATE_CONFIG": str(tmp_path / "absent.conf")})


def test_invalid_config_stops_the_service_at_startup(monkeypatch, config_file):
    """``datagate start`` gives up before it binds a port."""
    monkeypatch.setattr(sys, "argv", ["datagate", "start"])
    for name, value in config_file("REQUIRE_TLS=sometimes").items():
        monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit):
        datagate.main()
