"""Spec section: Configuration -- precedence, the config file format, startup failure."""

import pytest

from datagate_core.config import ConfigurationError, load_settings
from datagate_core.server import create_app


# Phrase: "1. Built-in defaults"
# Context: the defaults column of the settings table, with nothing configured.
def test_defaults_when_nothing_is_configured(monkeypatch):
    monkeypatch.delenv("STORAGE_DIR", raising=False)
    settings = load_settings()

    assert settings.max_source_size is None
    assert settings.origin_allowlist == ()
    assert settings.require_tls is False
    assert settings.cache_enabled is True
    assert settings.storage_dir


# Phrase: "| `STORAGE_DIR` | path | implementation-defined |"
# Context: the default is unspecified but must exist (AMBIGUITIES T70).
def test_storage_dir_has_an_implementation_defined_default(monkeypatch):
    monkeypatch.delenv("STORAGE_DIR", raising=False)

    assert isinstance(load_settings().storage_dir, str)


# Phrase: "2. `DATAGATE_CONFIG` file"
# Context: the file overrides the built-in defaults (AMBIGUITIES T56).
def test_config_file_overrides_the_defaults(config_file):
    config_file("MAX_SOURCE_SIZE=2048\nREQUIRE_TLS=true\nCACHE_ENABLED=off\n")
    settings = load_settings()

    assert settings.max_source_size == 2048
    assert settings.require_tls is True
    assert settings.cache_enabled is False


# Phrase: "3. Direct environment variables"
# Context: the environment wins over the same key in the file (AMBIGUITIES T56).
def test_environment_overrides_the_config_file(config_file, monkeypatch):
    config_file("MAX_SOURCE_SIZE=2048\nREQUIRE_TLS=true\n")
    monkeypatch.setenv("MAX_SOURCE_SIZE", "10")

    settings = load_settings()

    assert settings.max_source_size == 10
    assert settings.require_tls is True


# Phrase: "3. Direct environment variables"
# Context: keys the file does not mention still come from the environment.
def test_environment_supplies_keys_absent_from_the_file(config_file, monkeypatch):
    config_file("REQUIRE_TLS=on\n")
    monkeypatch.setenv("ORIGIN_ALLOWLIST", "example.com")

    assert load_settings().origin_allowlist == ("example.com",)


# Phrase: "The config file is `KEY=VALUE` lines"
# Context: surrounding whitespace around the key and the value is not part of either.
def test_config_file_trims_around_the_key_and_value(config_file):
    config_file("  MAX_SOURCE_SIZE = 64  \n")

    assert load_settings().max_source_size == 64


# Phrase: "The config file is `KEY=VALUE` lines"
# Context: a value may itself contain `=`; only the first one separates.
def test_config_file_splits_on_the_first_equals(config_file, monkeypatch, tmp_path):
    monkeypatch.delenv("STORAGE_DIR")
    config_file(f"STORAGE_DIR={tmp_path}/a=b\n")

    assert load_settings().storage_dir == f"{tmp_path}/a=b"


# Phrase: "with commas for list values"
def test_config_file_splits_list_values_on_commas(config_file):
    config_file("ORIGIN_ALLOWLIST=example.com,cdn.example.org,internal.test\n")

    assert load_settings().origin_allowlist == (
        "example.com",
        "cdn.example.org",
        "internal.test",
    )


# Phrase: "with commas for list values"
# Context: the same comma syntax applies to a direct environment variable.
def test_environment_splits_list_values_on_commas(monkeypatch):
    monkeypatch.setenv("ORIGIN_ALLOWLIST", "a.test, b.test ,c.test")

    assert load_settings().origin_allowlist == ("a.test", "b.test", "c.test")


# Phrase: "blank/comment lines ignored"
def test_config_file_ignores_blank_and_comment_lines(config_file):
    config_file(
        "# datagate configuration\n"
        "\n"
        "   \n"
        "MAX_SOURCE_SIZE=32\n"
        "\t# indented comment\n"
        "REQUIRE_TLS=yes\n"
    )
    settings = load_settings()

    assert (settings.max_source_size, settings.require_tls) == (32, True)


# Phrase: "blank/comment lines ignored"
# Context: `#` only starts a comment at the start of a line (AMBIGUITIES T57).
def test_hash_inside_a_value_is_not_a_comment(config_file):
    config_file("ORIGIN_ALLOWLIST=a#b.test\n")

    assert load_settings().origin_allowlist == ("a#b.test",)


# Phrase: "The config file is `KEY=VALUE` lines"
# Context: keys that are not settings are ignored (AMBIGUITIES T58).
def test_unknown_keys_are_ignored(config_file):
    config_file("PATH=/usr/bin\nUNRELATED=1\nMAX_SOURCE_SIZE=5\n")

    assert load_settings().max_source_size == 5


# Phrase: "The config file is `KEY=VALUE` lines"
# Context: a repeated key takes its last assignment (AMBIGUITIES T59).
def test_a_repeated_key_takes_the_last_assignment(config_file):
    config_file("MAX_SOURCE_SIZE=1\nMAX_SOURCE_SIZE=2\n")

    assert load_settings().max_source_size == 2


# Phrase: "Invalid config ... at startup returns an error and exits."
# Context: a line that is neither blank, comment nor assignment (AMBIGUITIES T60).
@pytest.mark.parametrize("line", ["nonsense", "=5", "   =  ", "MAX_SOURCE_SIZE"])
def test_a_malformed_line_fails_startup(config_file, line):
    config_file(f"REQUIRE_TLS=true\n{line}\n")

    with pytest.raises(ConfigurationError):
        load_settings()


# Phrase: "Invalid config ... at startup returns an error and exits."
# Context: the message names the file so an operator can act on it.
def test_a_malformed_line_failure_names_the_file(config_file):
    path = config_file("nonsense\n")

    with pytest.raises(ConfigurationError, match=str(path)):
        load_settings()


# Phrase: "... or read failure at startup returns an error and exits."
def test_a_missing_config_file_fails_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAGATE_CONFIG", str(tmp_path / "absent.conf"))

    with pytest.raises(ConfigurationError):
        load_settings()


# Phrase: "... or read failure at startup returns an error and exits."
# Context: a directory in place of the file cannot be read either.
def test_an_unreadable_config_file_fails_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAGATE_CONFIG", str(tmp_path))

    with pytest.raises(ConfigurationError):
        load_settings()


# Phrase: "Invalid config or read failure at startup returns an error and exits."
# Context: building the application is what performs startup (AMBIGUITIES T53).
def test_building_the_app_fails_on_invalid_config(monkeypatch):
    monkeypatch.setenv("MAX_SOURCE_SIZE", "lots")

    with pytest.raises(ConfigurationError):
        create_app()


# Phrase: "Invalid config or read failure at startup returns an error and exits."
# Context: the CLI turns the failure into a non-zero exit.
def test_the_cli_exits_non_zero_on_invalid_config(monkeypatch):
    import datagate

    monkeypatch.setenv("ORIGIN_ALLOWLIST", "ok.test")
    monkeypatch.setenv("REQUIRE_TLS", "perhaps")

    with pytest.raises(SystemExit) as exit_info:
        datagate.main(["start"])

    assert exit_info.value.code != 0


# Phrase: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`"
@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_boolean_true_spellings(monkeypatch, value):
    monkeypatch.setenv("REQUIRE_TLS", value)

    assert load_settings().require_tls is True


# Phrase: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`"
@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_boolean_false_spellings(monkeypatch, value):
    monkeypatch.setenv("REQUIRE_TLS", value)

    assert load_settings().require_tls is False


# Phrase: "(case-insensitive, trimmed)"
@pytest.mark.parametrize("value", ["TRUE", "Yes", "oN", " true", "on\t", "\n1 "])
def test_boolean_values_are_case_folded_and_trimmed(monkeypatch, value):
    monkeypatch.setenv("REQUIRE_TLS", value)

    assert load_settings().require_tls is True


# Phrase: "Boolean values are strict"
# Context: anything outside the vocabulary is invalid config.
@pytest.mark.parametrize("value", ["maybe", "2", "-1", "y", "", "   ", "truthy"])
def test_boolean_values_outside_the_vocabulary_fail_startup(monkeypatch, value):
    monkeypatch.setenv("CACHE_ENABLED", value)

    with pytest.raises(ConfigurationError):
        load_settings()


# Phrase: "| `MAX_SOURCE_SIZE` | integer bytes | unset |"
# Context: a plain decimal integer, trimmed (AMBIGUITIES T61).
@pytest.mark.parametrize("raw, expected", [("0", 0), ("1", 1), (" 4096 ", 4096)])
def test_max_source_size_accepts_integers(monkeypatch, raw, expected):
    monkeypatch.setenv("MAX_SOURCE_SIZE", raw)

    assert load_settings().max_source_size == expected


# Phrase: "| `MAX_SOURCE_SIZE` | integer bytes | unset |"
# Context: anything that is not a non-negative integer is invalid (AMBIGUITIES T61).
@pytest.mark.parametrize("raw", ["-1", "1.5", "10MB", "1_000", "", "0x10", "1e3"])
def test_max_source_size_rejects_non_integers(monkeypatch, raw):
    monkeypatch.setenv("MAX_SOURCE_SIZE", raw)

    with pytest.raises(ConfigurationError):
        load_settings()


# Phrase: "| `ORIGIN_ALLOWLIST` | list of domain suffixes | unset |"
# Context: a value that parses to nothing means unset (AMBIGUITIES T64).
@pytest.mark.parametrize("raw", ["", "  ", ",", " , ,"])
def test_an_empty_allowlist_value_means_unset(monkeypatch, raw):
    monkeypatch.setenv("ORIGIN_ALLOWLIST", raw)

    assert load_settings().origin_allowlist == ()


# Phrase: "| `ORIGIN_ALLOWLIST` | list of domain suffixes | unset |"
# Context: a leading dot on a suffix is dropped (AMBIGUITIES T64).
def test_allowlist_entries_drop_a_leading_dot(monkeypatch):
    monkeypatch.setenv("ORIGIN_ALLOWLIST", ".example.com")

    assert load_settings().origin_allowlist == ("example.com",)


# Phrase: "2. `DATAGATE_CONFIG` file"
# Context: every setting is reachable from the file, not just some.
def test_every_setting_can_come_from_the_file(config_file, monkeypatch, tmp_path):
    monkeypatch.delenv("STORAGE_DIR")
    config_file(
        f"MAX_SOURCE_SIZE=99\n"
        f"ORIGIN_ALLOWLIST=a.test,b.test\n"
        f"REQUIRE_TLS=1\n"
        f"STORAGE_DIR={tmp_path / 'from-file'}\n"
        f"CACHE_ENABLED=no\n"
    )
    settings = load_settings()

    assert settings.max_source_size == 99
    assert settings.origin_allowlist == ("a.test", "b.test")
    assert settings.require_tls is True
    assert settings.storage_dir == str(tmp_path / "from-file")
    assert settings.cache_enabled is False
