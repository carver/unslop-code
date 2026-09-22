"""Spec section: Configuration (sources, precedence, file format, settings table)."""

import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

from datagate_app.config import ConfigurationError, load_settings

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def config_file(tmp_path):
    """Write a `DATAGATE_CONFIG` file and hand back an environment naming it."""

    def _config_file(text, **environ):
        path = tmp_path / "datagate.conf"
        path.write_text(text)
        return {"DATAGATE_CONFIG": str(path), **environ}

    return _config_file


# Phrase: "1. Built-in defaults" (context: nothing configured at all)
def test_defaults_apply_when_nothing_is_configured():
    settings = load_settings({})

    assert settings.max_source_size is None
    assert settings.origin_allowlist == ()
    assert settings.require_tls is False
    assert settings.cache_enabled is True


# Phrase: "STORAGE_DIR | path | implementation-defined"
def test_storage_dir_has_an_implementation_defined_default():
    assert load_settings({}).storage_dir == pathlib.Path(tempfile.gettempdir()) / "datagate"


# Phrase: "2. `DATAGATE_CONFIG` file" (context: it overrides the built-in defaults)
def test_config_file_overrides_defaults(config_file):
    settings = load_settings(config_file("MAX_SOURCE_SIZE=4096\nREQUIRE_TLS=true\n"))

    assert settings.max_source_size == 4096
    assert settings.require_tls is True


# Phrase: "3. Direct environment variables" (context: highest precedence)
def test_environment_overrides_the_config_file(config_file):
    environ = config_file("MAX_SOURCE_SIZE=4096\n", MAX_SOURCE_SIZE="10")

    assert load_settings(environ).max_source_size == 10


# Phrase: "in order of precedence" (context: a setting only the file names keeps the file's value)
def test_environment_overrides_only_the_keys_it_names(config_file):
    environ = config_file("MAX_SOURCE_SIZE=4096\nREQUIRE_TLS=on\n", REQUIRE_TLS="off")

    settings = load_settings(environ)

    assert (settings.max_source_size, settings.require_tls) == (4096, False)


# Phrase: "The config file is `KEY=VALUE` lines"
def test_config_file_reads_key_value_lines(config_file):
    settings = load_settings(config_file("CACHE_ENABLED=off\nSTORAGE_DIR=/tmp/datagate-test\n"))

    assert settings.cache_enabled is False
    assert settings.storage_dir == pathlib.Path("/tmp/datagate-test")


# Phrase: "`KEY=VALUE` lines" (context: surrounding whitespace around key and value is not part of either)
def test_config_file_trims_keys_and_values(config_file):
    settings = load_settings(config_file("  MAX_SOURCE_SIZE = 512  \n"))

    assert settings.max_source_size == 512


# Phrase: "with commas for list values"
def test_config_file_splits_list_values_on_commas(config_file):
    settings = load_settings(config_file("ORIGIN_ALLOWLIST=example.com,foo.test\n"))

    assert settings.origin_allowlist == ("example.com", "foo.test")


# Phrase: "with commas for list values" (context: entries are trimmed and empties dropped)
def test_list_entries_are_trimmed(config_file):
    settings = load_settings(config_file("ORIGIN_ALLOWLIST= a.test , b.test ,\n"))

    assert settings.origin_allowlist == ("a.test", "b.test")


# Phrase: "with commas for list values" (context: the same list spelling works in the environment)
def test_list_values_split_in_the_environment_too():
    assert load_settings({"ORIGIN_ALLOWLIST": "a.test,b.test"}).origin_allowlist == ("a.test", "b.test")


# Phrase: "blank/comment lines ignored"
def test_blank_and_comment_lines_are_ignored(config_file):
    text = "\n# a comment\n   \nMAX_SOURCE_SIZE=7\n   # indented comment\n\n"

    assert load_settings(config_file(text)).max_source_size == 7


# Phrase: "Invalid config ... at startup returns an error and exits." (context: a line that is not KEY=VALUE)
def test_a_line_without_an_equals_sign_is_invalid(config_file):
    with pytest.raises(ConfigurationError):
        load_settings(config_file("MAX_SOURCE_SIZE\n"))


# Phrase: "Invalid config ..." (context: MAX_SOURCE_SIZE is integer bytes)
@pytest.mark.parametrize("value", ["abc", "4.5", "-1", "1e3", "10MB", "0x10"])
def test_non_integer_max_source_size_is_invalid(value):
    with pytest.raises(ConfigurationError):
        load_settings({"MAX_SOURCE_SIZE": value})


# Phrase: "... or read failure at startup returns an error and exits."
def test_unreadable_config_file_is_an_error(tmp_path):
    with pytest.raises(ConfigurationError):
        load_settings({"DATAGATE_CONFIG": str(tmp_path / "missing.conf")})


# Phrase: "Invalid config or read failure at startup returns an error and exits." (context: the process exits)
def test_invalid_config_stops_the_start_command():
    result = subprocess.run(
        [sys.executable, str(ROOT / "datagate.py"), "start", "--port", "8124"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "REQUIRE_TLS": "perhaps"},
        timeout=60,
    )

    assert result.returncode != 0
    assert "REQUIRE_TLS" in result.stderr


# Phrase: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`"
@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_true_booleans(value):
    assert load_settings({"REQUIRE_TLS": value}).require_tls is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_false_booleans(value):
    assert load_settings({"REQUIRE_TLS": value}).require_tls is False


# Phrase: "(case-insensitive, trimmed)"
@pytest.mark.parametrize("value", ["TRUE", "Yes", " on ", "\tOn\n"])
def test_booleans_are_case_insensitive_and_trimmed(value):
    assert load_settings({"REQUIRE_TLS": value}).require_tls is True


# Phrase: "Boolean values are strict" (context: anything outside the eight literals)
@pytest.mark.parametrize("value", ["maybe", "2", "", "y", "t", "true false", "enabled"])
def test_other_boolean_values_are_invalid(value):
    with pytest.raises(ConfigurationError):
        load_settings({"CACHE_ENABLED": value})


# Phrase: "`MAX_SOURCE_SIZE` | integer bytes | unset" (context: T60 -- an empty value leaves it unset)
def test_empty_values_leave_optional_settings_unset():
    settings = load_settings({"MAX_SOURCE_SIZE": "", "ORIGIN_ALLOWLIST": "", "STORAGE_DIR": ""})

    assert settings.max_source_size is None
    assert settings.origin_allowlist == ()
    assert settings.storage_dir == load_settings({}).storage_dir


# Phrase: "The config file is `KEY=VALUE` lines" (context: T59 -- keys outside the settings table)
def test_unknown_keys_are_ignored(config_file):
    assert load_settings(config_file("UNKNOWN_KEY=whatever\nREQUIRE_TLS=on\n")).require_tls is True
