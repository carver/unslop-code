"""Spec section: configuration sources, the config file format, and the settings table."""

from pathlib import Path

import pytest

from datagate_core.config import Settings, load_settings
from datagate_core.errors import ConfigurationError
from datagate_core.server import create_app


def settings_from(environ):
    """Load settings from an explicit environment, as `create_app()` does at startup."""
    return load_settings(environ)


# Phrase: "Service configuration sources, in order of precedence: 1. Built-in
# defaults" - an empty environment yields every default in the settings table.
def test_built_in_defaults_apply_when_nothing_is_configured():
    settings = settings_from({})

    assert settings.max_source_size is None
    assert settings.origin_allowlist == ()
    assert settings.require_tls is False
    assert settings.cache_enabled is True
    assert isinstance(settings.storage_dir, Path)


# Phrase: "2. `DATAGATE_CONFIG` file" - the file supplies values the defaults do not.
def test_config_file_supplies_values(tmp_path):
    path = tmp_path / "datagate.conf"
    path.write_text("MAX_SOURCE_SIZE=2048\nREQUIRE_TLS=true\n", encoding="utf-8")

    settings = settings_from({"DATAGATE_CONFIG": str(path)})

    assert settings.max_source_size == 2048
    assert settings.require_tls is True


# Phrase: "in order of precedence: ... 2. `DATAGATE_CONFIG` file 3. Direct
# environment variables" - the environment wins over the file (T57).
def test_environment_overrides_the_config_file(tmp_path):
    path = tmp_path / "datagate.conf"
    path.write_text("MAX_SOURCE_SIZE=10\nCACHE_ENABLED=off\n", encoding="utf-8")

    settings = settings_from(
        {"DATAGATE_CONFIG": str(path), "MAX_SOURCE_SIZE": "99", "CACHE_ENABLED": "on"}
    )

    assert settings.max_source_size == 99
    assert settings.cache_enabled is True


# Phrase: "in order of precedence" - a key only the file sets survives while
# another key is overridden from the environment.
def test_file_values_survive_an_unrelated_environment_override(tmp_path):
    path = tmp_path / "datagate.conf"
    path.write_text("REQUIRE_TLS=on\nMAX_SOURCE_SIZE=10\n", encoding="utf-8")

    settings = settings_from({"DATAGATE_CONFIG": str(path), "MAX_SOURCE_SIZE": "20"})

    assert (settings.require_tls, settings.max_source_size) == (True, 20)


# Phrase: "The config file is `KEY=VALUE` lines" - keys and values are trimmed,
# and a value keeps any `=` after the first one (T58).
def test_config_file_lines_are_key_equals_value(tmp_path):
    path = tmp_path / "datagate.conf"
    path.write_text("  MAX_SOURCE_SIZE =  4096  \nSTORAGE_DIR=/tmp/a=b\n", encoding="utf-8")

    settings = settings_from({"DATAGATE_CONFIG": str(path)})

    assert settings.max_source_size == 4096
    assert settings.storage_dir == Path("/tmp/a=b")


# Phrase: "with commas for list values" - `ORIGIN_ALLOWLIST` splits on commas.
def test_commas_separate_list_values(tmp_path):
    path = tmp_path / "datagate.conf"
    path.write_text("ORIGIN_ALLOWLIST=a.test, b.test ,c.test\n", encoding="utf-8")

    assert settings_from({"DATAGATE_CONFIG": str(path)}).origin_allowlist == (
        "a.test",
        "b.test",
        "c.test",
    )


# Phrase: "with commas for list values" - the same splitting applies to the
# environment variable, so both sources spell a list the same way.
def test_commas_separate_list_values_from_the_environment():
    assert settings_from({"ORIGIN_ALLOWLIST": "a.test,b.test"}).origin_allowlist == (
        "a.test",
        "b.test",
    )


# Phrase: "blank/comment lines ignored".
def test_blank_and_comment_lines_are_ignored(tmp_path):
    path = tmp_path / "datagate.conf"
    path.write_text(
        "# leading comment\n\n   \nMAX_SOURCE_SIZE=7\n  # indented comment\n\n",
        encoding="utf-8",
    )

    assert settings_from({"DATAGATE_CONFIG": str(path)}).max_source_size == 7


# Phrase: "Invalid config ... at startup returns an error and exits" - a line
# that is neither blank, comment nor `KEY=VALUE` is fatal (T58).
def test_a_line_without_an_equals_sign_is_invalid_config(tmp_path):
    path = tmp_path / "datagate.conf"
    path.write_text("MAX_SOURCE_SIZE=7\nthis is not a setting\n", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        settings_from({"DATAGATE_CONFIG": str(path)})


# Phrase: "Invalid config ... returns an error and exits" - an unreadable value
# for a typed setting is fatal wherever it came from.
@pytest.mark.parametrize(
    "environ",
    [
        {"MAX_SOURCE_SIZE": "lots"},
        {"MAX_SOURCE_SIZE": "1.5"},
        {"MAX_SOURCE_SIZE": "10MB"},
        {"MAX_SOURCE_SIZE": "-1"},
        {"REQUIRE_TLS": "maybe"},
        {"CACHE_ENABLED": "sometimes"},
    ],
)
def test_unreadable_values_are_invalid_config(environ):
    with pytest.raises(ConfigurationError):
        settings_from(environ)


# Phrase: "Invalid config ... returns an error and exits" - the message names the
# setting, so an operator can find it.
def test_the_error_names_the_offending_setting():
    with pytest.raises(ConfigurationError, match="MAX_SOURCE_SIZE"):
        settings_from({"MAX_SOURCE_SIZE": "lots"})


# Phrase: "... or read failure at startup returns an error and exits" -
# `DATAGATE_CONFIG` naming a file that is not there is a read failure (T59).
def test_a_missing_config_file_is_a_read_failure(tmp_path):
    with pytest.raises(ConfigurationError):
        settings_from({"DATAGATE_CONFIG": str(tmp_path / "absent.conf")})


# Phrase: "... read failure ..." - a directory cannot be read as a config file.
def test_a_config_path_that_is_a_directory_is_a_read_failure(tmp_path):
    with pytest.raises(ConfigurationError):
        settings_from({"DATAGATE_CONFIG": str(tmp_path)})


# Phrase: "2. `DATAGATE_CONFIG` file" - an unset or empty variable names no file,
# so startup proceeds on defaults (T59).
@pytest.mark.parametrize("environ", [{}, {"DATAGATE_CONFIG": ""}])
def test_no_config_file_is_not_a_read_failure(environ):
    assert settings_from(environ).max_source_size is None


# Phrase: the settings table lists five settings; keys outside it are ignored (T61).
def test_unknown_config_keys_are_ignored(tmp_path):
    path = tmp_path / "datagate.conf"
    path.write_text("UNRELATED=1\nMAX_SOURCE_SIZE=5\n", encoding="utf-8")

    assert settings_from({"DATAGATE_CONFIG": str(path)}).max_source_size == 5


# Phrase: "| `MAX_SOURCE_SIZE` | integer bytes | unset |" - a plain decimal
# integer, including zero (T62).
@pytest.mark.parametrize("value,expected", [("0", 0), ("1", 1), ("1048576", 1048576)])
def test_max_source_size_reads_as_an_integer(value, expected):
    assert settings_from({"MAX_SOURCE_SIZE": value}).max_source_size == expected


# Phrase: "| `ORIGIN_ALLOWLIST` | list of domain suffixes | unset |" - an empty
# value means unset, the same as never configuring it (T60).
@pytest.mark.parametrize("value", ["", "  ", ",", " , "])
def test_an_empty_allowlist_value_means_unset(value):
    assert settings_from({"ORIGIN_ALLOWLIST": value}).origin_allowlist == ()


# Phrase: "| `MAX_SOURCE_SIZE` | integer bytes | unset |" - an empty value means
# unset rather than a limit of zero (T60).
def test_an_empty_max_source_size_means_unset():
    assert settings_from({"MAX_SOURCE_SIZE": ""}).max_source_size is None


# Phrase: "| `STORAGE_DIR` | path | implementation-defined |".
def test_storage_dir_reads_as_a_path(tmp_path):
    assert settings_from({"STORAGE_DIR": str(tmp_path / "here")}) == Settings(
        max_source_size=None,
        origin_allowlist=(),
        require_tls=False,
        storage_dir=tmp_path / "here",
        cache_enabled=True,
    )


# Phrase: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`".
@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_boolean_true_spellings(value):
    assert settings_from({"REQUIRE_TLS": value}).require_tls is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_boolean_false_spellings(value):
    assert settings_from({"REQUIRE_TLS": value}).require_tls is False


# Phrase: "(case-insensitive, trimmed)".
@pytest.mark.parametrize("value", ["TRUE", "Yes", "  on  ", "\tON\n", " 1 "])
def test_boolean_values_are_case_insensitive_and_trimmed(value):
    assert settings_from({"REQUIRE_TLS": value}).require_tls is True


# Phrase: "Boolean values are strict" - a value outside the two lists, including
# one that only trims to empty, is invalid config.
@pytest.mark.parametrize("value", ["", "  ", "maybe", "2", "y", "t", "-1", "onoff"])
def test_boolean_values_outside_the_two_lists_are_invalid(value):
    with pytest.raises(ConfigurationError):
        settings_from({"REQUIRE_TLS": value})


# Phrase: "| `CACHE_ENABLED` | boolean | `true` |" - the same strict booleans,
# and the same default the caching spec gave it.
def test_cache_enabled_is_a_boolean_defaulting_to_true():
    assert settings_from({}).cache_enabled is True
    assert settings_from({"CACHE_ENABLED": "no"}).cache_enabled is False


# Phrase: "Invalid startup config | N/A | startup failure" - `create_app()`
# refuses to build an application rather than serving with a guessed value.
def test_invalid_config_stops_create_app(settings_env):
    settings_env.setenv("REQUIRE_TLS", "maybe")

    with pytest.raises(ConfigurationError):
        create_app()


# Phrase: "Invalid config or read failure at startup returns an error and exits"
# - the same is true of a config file that cannot be read.
def test_unreadable_config_file_stops_create_app(settings_env, tmp_path):
    settings_env.setenv("DATAGATE_CONFIG", str(tmp_path / "absent.conf"))

    with pytest.raises(ConfigurationError):
        create_app()


# Phrase: "Invalid startup config | N/A | startup failure" - the server process
# exits non-zero and never listens (T49).
def test_invalid_config_stops_the_server_process(tmp_path):
    import subprocess
    import sys

    log = (tmp_path / "startup.log").open("w")
    try:
        completed = subprocess.run(
            [sys.executable, "datagate.py", "start", "--port", "8125"],
            cwd=Path(__file__).resolve().parent.parent,
            env={"PATH": "/usr/bin:/bin", "MAX_SOURCE_SIZE": "enormous"},
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    finally:
        log.close()

    assert completed.returncode != 0
    assert "MAX_SOURCE_SIZE" in (tmp_path / "startup.log").read_text()


# Phrase: "2. `DATAGATE_CONFIG` file" - a setting taken from the file changes
# how the running service behaves, not just what `load_settings` returns.
def test_a_file_setting_reaches_the_running_service(config_file, configured_client):
    config_file("ORIGIN_ALLOWLIST=example.test\n")
    client = configured_client()

    assert client.get("/datasets/missing").status_code == 403
    assert client.get(
        "/datasets/missing", headers={"Referer": "http://example.test/"}
    ).status_code == 404


# Phrase: "3. Direct environment variables" - the environment overrides the same
# key in the file, end to end.
def test_an_environment_override_reaches_the_running_service(
    config_file, configured_client, settings_env
):
    config_file("ORIGIN_ALLOWLIST=example.test\n")
    settings_env.setenv("ORIGIN_ALLOWLIST", "other.test")
    client = configured_client()

    assert client.get(
        "/datasets/missing", headers={"Referer": "http://example.test/"}
    ).status_code == 403
    assert client.get(
        "/datasets/missing", headers={"Referer": "http://other.test/"}
    ).status_code == 404
