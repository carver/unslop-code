"""Tests for settings: the config file, the precedence of the sources, and startup failures."""

import subprocess
import sys
from pathlib import Path

import pytest

from config import CONFIG_FILE_VAR, DEFAULT_STORAGE_DIR, load_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def write_config(tmp_path, text: str) -> dict[str, str]:
    """Write a config file and return the environment that points the loader at it."""
    path = tmp_path / "datagate.conf"
    path.write_text(text, encoding="utf-8")
    return {CONFIG_FILE_VAR: str(path)}


def test_defaults_apply_without_any_configuration():
    settings = load_settings({})
    assert settings.max_source_size is None
    assert settings.origin_allowlist == ()
    assert settings.require_tls is False
    assert settings.storage_dir == DEFAULT_STORAGE_DIR
    assert settings.cache_enabled is True


def test_config_file_sets_every_setting(tmp_path):
    environ = write_config(
        tmp_path,
        "MAX_SOURCE_SIZE=2048\n"
        "ORIGIN_ALLOWLIST=example.com, docs.example.org\n"
        "REQUIRE_TLS=yes\n"
        "STORAGE_DIR=/var/lib/datagate\n"
        "CACHE_ENABLED=off\n",
    )
    settings = load_settings(environ)
    assert settings.max_source_size == 2048
    assert settings.origin_allowlist == ("example.com", "docs.example.org")
    assert settings.require_tls is True
    assert settings.storage_dir == Path("/var/lib/datagate")
    assert settings.cache_enabled is False


def test_blank_and_comment_lines_are_ignored(tmp_path):
    environ = write_config(
        tmp_path, "\n# the service's own storage\n\n   \nMAX_SOURCE_SIZE = 64 \n\n"
    )
    assert load_settings(environ).max_source_size == 64


def test_environment_overrides_the_config_file(tmp_path):
    environ = write_config(tmp_path, "MAX_SOURCE_SIZE=10\nREQUIRE_TLS=on\n")
    settings = load_settings({**environ, "MAX_SOURCE_SIZE": "99"})
    assert settings.max_source_size == 99
    assert settings.require_tls is True


def test_settings_the_file_omits_keep_their_defaults(tmp_path):
    environ = write_config(tmp_path, "REQUIRE_TLS=true\n")
    assert load_settings(environ).max_source_size is None


def test_an_empty_allowlist_value_is_no_allowlist(tmp_path):
    environ = write_config(tmp_path, "ORIGIN_ALLOWLIST=\n")
    assert load_settings(environ).origin_allowlist == ()


def test_allowlist_suffixes_are_normalised(tmp_path):
    environ = write_config(tmp_path, "ORIGIN_ALLOWLIST=.Example.COM,,  reports.example.net  \n")
    assert load_settings(environ).origin_allowlist == ("example.com", "reports.example.net")


@pytest.mark.parametrize(
    "text",
    [
        "MAX_SOURCE_SIZE=lots\n",
        "MAX_SOURCE_SIZE=-1\n",
        "MAX_SOURCE_SIZE=1.5\n",
        "REQUIRE_TLS=perhaps\n",
        "CACHE_ENABLED=\n",
        "MAX_SOURCE_SIZE\n",
        "STORAGE_SIZE=10\n",
    ],
)
def test_an_invalid_config_file_is_rejected(tmp_path, text):
    with pytest.raises(ValueError):
        load_settings(write_config(tmp_path, text))


def test_an_unreadable_config_file_is_reported(tmp_path):
    with pytest.raises(OSError):
        load_settings({CONFIG_FILE_VAR: str(tmp_path / "absent.conf")})


@pytest.mark.parametrize(
    "environ",
    [
        {"CACHE_ENABLED": "maybe"},
        {"MAX_SOURCE_SIZE": "big"},
        {CONFIG_FILE_VAR: "/nonexistent/datagate.conf"},
    ],
)
def test_invalid_configuration_stops_the_service_starting(environ):
    result = subprocess.run(
        [sys.executable, "datagate.py", "start"],
        cwd=PROJECT_ROOT,
        env={"PATH": "", **environ},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "datagate:" in result.stderr
