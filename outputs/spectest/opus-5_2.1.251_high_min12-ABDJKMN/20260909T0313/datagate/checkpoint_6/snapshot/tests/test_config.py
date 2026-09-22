"""Spec section: Configuration (sources, precedence, file format, settings).

    Service configuration sources, in order of precedence:
    1. Built-in defaults
    2. `DATAGATE_CONFIG` file
    3. Direct environment variables
    The config file is `KEY=VALUE` lines, with commas for list values,
    blank/comment lines ignored.
    Invalid config or read failure at startup returns an error and exits.
"""

import os

import pytest

import datagate
from conftest import free_port as _free_port


# ---------------------------------------------------------------------------
# 1. Built-in defaults
# ---------------------------------------------------------------------------


# Phrase: "1. Built-in defaults" / table row "`MAX_SOURCE_SIZE` | integer bytes | unset"
def test_max_source_size_defaults_to_unset(configure):
    assert configure() is None
    assert datagate.MAX_SOURCE_SIZE is None


# Phrase: table row "`ORIGIN_ALLOWLIST` | list of domain suffixes | unset"
def test_origin_allowlist_defaults_to_unset(configure):
    assert configure() is None
    assert not datagate.ORIGIN_ALLOWLIST


# Phrase: table row "`REQUIRE_TLS` | boolean | `false`"
def test_require_tls_defaults_to_false(configure):
    assert configure() is None
    assert datagate.REQUIRE_TLS is False


# Phrase: table row "`CACHE_ENABLED` | boolean | `true`"
def test_cache_enabled_defaults_to_true(configure):
    assert configure() is None
    assert datagate.CACHE_ENABLED is True


# Phrase: table row "`STORAGE_DIR` | path | implementation-defined"
# Context: whatever the built-in default is, it must be a usable path string.
def test_storage_dir_default_is_a_path(_config_snapshot):
    assert datagate.load_config({}) is None
    assert isinstance(datagate.STORAGE_DIR, str)
    assert datagate.STORAGE_DIR
    assert os.path.isdir(datagate.STORAGE_DIR)


# ---------------------------------------------------------------------------
# 2. `DATAGATE_CONFIG` file  --  format
# ---------------------------------------------------------------------------


# Phrase: "The config file is `KEY=VALUE` lines"
def test_config_file_sets_a_scalar_setting(configure, config_file):
    path = config_file("MAX_SOURCE_SIZE=4096\n")
    assert configure(DATAGATE_CONFIG=path) is None
    assert datagate.MAX_SOURCE_SIZE == 4096


# Phrase: "The config file is `KEY=VALUE` lines"
# Context: several settings in one file.
def test_config_file_sets_several_settings(configure, config_file):
    path = config_file("MAX_SOURCE_SIZE=10\nREQUIRE_TLS=true\nCACHE_ENABLED=off\n")
    assert configure(DATAGATE_CONFIG=path) is None
    assert datagate.MAX_SOURCE_SIZE == 10
    assert datagate.REQUIRE_TLS is True
    assert datagate.CACHE_ENABLED is False


# Phrase: "with commas for list values"
def test_config_file_splits_list_values_on_commas(configure, config_file):
    path = config_file("ORIGIN_ALLOWLIST=example.com,other.org\n")
    assert configure(DATAGATE_CONFIG=path) is None
    assert list(datagate.ORIGIN_ALLOWLIST) == ["example.com", "other.org"]


# Phrase: "with commas for list values" -- context: entries are trimmed and
# empty entries dropped (AMBIGUITIES T82).
def test_list_entries_are_trimmed(configure, config_file):
    path = config_file("ORIGIN_ALLOWLIST= example.com , other.org ,\n")
    assert configure(DATAGATE_CONFIG=path) is None
    assert list(datagate.ORIGIN_ALLOWLIST) == ["example.com", "other.org"]


# Phrase: "blank/comment lines ignored"
def test_blank_and_comment_lines_are_ignored(configure, config_file):
    path = config_file(
        "\n"
        "# a leading comment\n"
        "   \n"
        "MAX_SOURCE_SIZE=7\n"
        "\t\n"
        "   # an indented comment\n"
        "REQUIRE_TLS=yes\n"
        "\n"
    )
    assert configure(DATAGATE_CONFIG=path) is None
    assert datagate.MAX_SOURCE_SIZE == 7
    assert datagate.REQUIRE_TLS is True


# Phrase: "The config file is `KEY=VALUE` lines" -- whitespace around the key
# and the value is not significant (AMBIGUITIES T66).
def test_whitespace_around_key_and_value(configure, config_file):
    path = config_file("  MAX_SOURCE_SIZE  =  99  \n")
    assert configure(DATAGATE_CONFIG=path) is None
    assert datagate.MAX_SOURCE_SIZE == 99


# Phrase: "The config file is `KEY=VALUE` lines" -- a value may itself contain
# "=" ; only the first one separates (AMBIGUITIES T66).
def test_only_the_first_equals_separates(configure, config_file, tmp_path):
    target = tmp_path / "a=b"
    path = config_file("STORAGE_DIR={}\n".format(target))
    assert configure(DATAGATE_CONFIG=path, STORAGE_DIR=None) is None
    assert datagate.STORAGE_DIR == str(target)


# Phrase: "The config file is `KEY=VALUE` lines" -- a key that datagate does
# not define is ignored rather than fatal (AMBIGUITIES T67).
def test_unknown_keys_are_ignored(configure, config_file):
    path = config_file("SOMETHING_ELSE=1\nMAX_SOURCE_SIZE=5\n")
    assert configure(DATAGATE_CONFIG=path) is None
    assert datagate.MAX_SOURCE_SIZE == 5


# Phrase: "The config file is `KEY=VALUE` lines" -- a repeated key takes its
# last value (AMBIGUITIES T81).
def test_repeated_key_last_wins(configure, config_file):
    path = config_file("MAX_SOURCE_SIZE=1\nMAX_SOURCE_SIZE=2\n")
    assert configure(DATAGATE_CONFIG=path) is None
    assert datagate.MAX_SOURCE_SIZE == 2


# ---------------------------------------------------------------------------
# 3. Direct environment variables, and precedence
# ---------------------------------------------------------------------------


# Phrase: "3. Direct environment variables"
def test_environment_variable_sets_a_setting(configure):
    assert configure(MAX_SOURCE_SIZE="1234") is None
    assert datagate.MAX_SOURCE_SIZE == 1234


# Phrase: "in order of precedence: ... 2. `DATAGATE_CONFIG` file ..." --
# the file beats the built-in default.
def test_config_file_beats_builtin_default(configure, config_file):
    path = config_file("CACHE_ENABLED=false\n")
    assert configure(DATAGATE_CONFIG=path) is None
    assert datagate.CACHE_ENABLED is False  # default is true


# Phrase: "in order of precedence: ... 3. Direct environment variables" --
# the environment beats the file.
def test_environment_beats_config_file(configure, config_file):
    path = config_file("MAX_SOURCE_SIZE=10\nREQUIRE_TLS=false\n")
    assert configure(DATAGATE_CONFIG=path, MAX_SOURCE_SIZE="20") is None
    assert datagate.MAX_SOURCE_SIZE == 20
    assert datagate.REQUIRE_TLS is False  # untouched by the environment


# Phrase: precedence is per setting -- a file value survives for the settings
# the environment does not mention.
def test_precedence_is_applied_per_setting(configure, config_file):
    path = config_file("MAX_SOURCE_SIZE=10\nCACHE_ENABLED=no\n")
    assert configure(DATAGATE_CONFIG=path, CACHE_ENABLED="yes") is None
    assert datagate.MAX_SOURCE_SIZE == 10
    assert datagate.CACHE_ENABLED is True


# Phrase: precedence for list settings replaces rather than merges
# (AMBIGUITIES T83).
def test_environment_list_replaces_the_file_list(configure, config_file):
    path = config_file("ORIGIN_ALLOWLIST=from-file.com\n")
    assert configure(DATAGATE_CONFIG=path, ORIGIN_ALLOWLIST="from-env.com") is None
    assert list(datagate.ORIGIN_ALLOWLIST) == ["from-env.com"]


# ---------------------------------------------------------------------------
# Boolean grammar
# ---------------------------------------------------------------------------


# Phrase: "Boolean values are strict: `1/true/yes/on` ... (case-insensitive, trimmed)"
@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "TRUE", "Yes", "ON", "TrUe"])
def test_true_boolean_tokens(configure, raw):
    assert configure(REQUIRE_TLS=raw, CACHE_ENABLED=raw) is None
    assert datagate.REQUIRE_TLS is True
    assert datagate.CACHE_ENABLED is True


# Phrase: "Boolean values are strict: ... `0/false/no/off` (case-insensitive, trimmed)"
@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "FALSE", "No", "OFF", "OfF"])
def test_false_boolean_tokens(configure, raw):
    assert configure(REQUIRE_TLS=raw, CACHE_ENABLED=raw) is None
    assert datagate.REQUIRE_TLS is False
    assert datagate.CACHE_ENABLED is False


# Phrase: "(case-insensitive, trimmed)" -- surrounding whitespace is stripped
# before the lookup. This resolves the whitespace half of AMBIGUITIES T56.
@pytest.mark.parametrize("raw", ["  true", "true  ", "  true  ", "\ttrue\n", " OFF "])
def test_boolean_values_are_trimmed(configure, raw):
    assert configure(REQUIRE_TLS=raw) is None
    assert datagate.REQUIRE_TLS is (raw.strip().lower() != "off")


# Phrase: "Boolean values are strict" -- nothing outside the eight tokens.
@pytest.mark.parametrize("raw", ["y", "n", "t", "f", "2", "-1", "enabled", "truthy",
                                 "tru e", "", "   ", "yes,no"])
def test_invalid_boolean_is_a_config_error(configure, raw):
    message = configure(REQUIRE_TLS=raw)
    assert isinstance(message, str) and message.strip()


# Phrase: "Boolean values are strict" -- also applies to values read from the
# `DATAGATE_CONFIG` file, not just direct environment variables.
def test_invalid_boolean_in_config_file_is_an_error(configure, config_file):
    path = config_file("CACHE_ENABLED=maybe\n")
    message = configure(DATAGATE_CONFIG=path)
    assert isinstance(message, str) and message.strip()


# ---------------------------------------------------------------------------
# `MAX_SOURCE_SIZE` grammar
# ---------------------------------------------------------------------------


# Phrase: "`MAX_SOURCE_SIZE` | integer bytes"
@pytest.mark.parametrize("raw,expected", [("0", 0), ("1", 1), ("1024", 1024),
                                          (" 2048 ", 2048), ("+7", 7)])
def test_valid_max_source_size_values(configure, raw, expected):
    assert configure(MAX_SOURCE_SIZE=raw) is None
    assert datagate.MAX_SOURCE_SIZE == expected


# Phrase: "`MAX_SOURCE_SIZE` | integer bytes" -- not a size expression, not a
# float, not negative (AMBIGUITIES T71).
@pytest.mark.parametrize("raw", ["10MB", "1k", "1.5", "1e6", "abc", "", "  ",
                                 "-1", "1_000", "0x10", "1,2"])
def test_invalid_max_source_size_is_a_config_error(configure, raw):
    message = configure(MAX_SOURCE_SIZE=raw)
    assert isinstance(message, str) and message.strip()


# ---------------------------------------------------------------------------
# "Invalid config or read failure at startup returns an error and exits."
# ---------------------------------------------------------------------------


# Phrase: "read failure at startup returns an error and exits" -- a
# DATAGATE_CONFIG naming a file that is not there (AMBIGUITIES T68).
def test_missing_config_file_is_an_error(configure, tmp_path):
    message = configure(DATAGATE_CONFIG=str(tmp_path / "nope.conf"))
    assert isinstance(message, str) and message.strip()


# Phrase: "read failure at startup returns an error and exits" -- a
# DATAGATE_CONFIG naming a directory cannot be read either.
def test_unreadable_config_file_is_an_error(configure, tmp_path):
    directory = tmp_path / "a-directory"
    directory.mkdir()
    message = configure(DATAGATE_CONFIG=str(directory))
    assert isinstance(message, str) and message.strip()


# Phrase: "Invalid config ... returns an error and exits" -- a line that is not
# `KEY=VALUE` (AMBIGUITIES T67).
@pytest.mark.parametrize("text", ["MAX_SOURCE_SIZE 10\n", "just-a-word\n",
                                  "MAX_SOURCE_SIZE=10\ngarbage line\n", "=5\n"])
def test_malformed_config_line_is_an_error(configure, config_file, text):
    message = configure(DATAGATE_CONFIG=config_file(text))
    assert isinstance(message, str) and message.strip()


# Phrase: "Invalid config ... returns an error and exits."
# Context: the process exits non-zero rather than serving.
def test_invalid_config_exits_without_serving(server):
    port = _free_port()
    instance = server("--port", str(port), name="config-invalid-bool",
                      env={"REQUIRE_TLS": "maybe"})
    assert instance.wait_for_exit() not in (None, 0), instance.log()
    assert instance.log().strip()


# Phrase: "read failure at startup returns an error and exits."
def test_unreadable_config_file_exits_without_serving(server, tmp_path):
    port = _free_port()
    instance = server("--port", str(port), name="config-missing-file",
                      env={"DATAGATE_CONFIG": str(tmp_path / "absent.conf")})
    assert instance.wait_for_exit() not in (None, 0), instance.log()
    assert instance.log().strip()


# Phrase: "Invalid config ... exits" -- context: a *valid* config file starts.
def test_valid_config_file_starts_normally(server, config_file, tmp_path):
    port = _free_port()
    path = config_file("# fine\nCACHE_ENABLED=on\nREQUIRE_TLS=off\n")
    instance = server("--port", str(port), name="config-valid",
                      env={"DATAGATE_CONFIG": path,
                           "STORAGE_DIR": str(tmp_path / "store")})
    assert instance.wait_until_listening("127.0.0.1", port), instance.log()
