"""Configuration: the sources, their precedence, the file syntax and validation."""

import pytest

from gateway.config import ConfigError, load_settings

BOOLEAN_SETTINGS = ("REQUIRE_TLS", "CACHE_ENABLED")
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


def config_file(tmp_path, text, name="datagate.conf"):
    """Write `text` as a config file and return the environment naming it."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return {"DATAGATE_CONFIG": str(path)}


# Spec: "Service configuration sources, in order of precedence: 1. Built-in
# defaults"
# Context: nothing configured at all, so every setting takes its documented
# default; `STORAGE_DIR` is implementation-defined but must be a path (T65).
def test_defaults_apply_when_nothing_is_configured():
    settings = load_settings({})
    assert settings.max_source_size is None
    assert settings.origin_allowlist == ()
    assert settings.require_tls is False
    assert settings.cache_enabled is True
    assert isinstance(settings.storage_dir, str) and settings.storage_dir


# Spec: "2. `DATAGATE_CONFIG` file"
# Context: a file supplies every setting, overriding the built-in defaults.
def test_config_file_overrides_the_defaults(tmp_path):
    environ = config_file(
        tmp_path,
        "MAX_SOURCE_SIZE=2048\n"
        "ORIGIN_ALLOWLIST=example.com\n"
        "REQUIRE_TLS=true\n"
        "STORAGE_DIR=/tmp/datagate-config\n"
        "CACHE_ENABLED=off\n",
    )
    settings = load_settings(environ)
    assert settings.max_source_size == 2048
    assert settings.origin_allowlist == ("example.com",)
    assert settings.require_tls is True
    assert settings.storage_dir == "/tmp/datagate-config"
    assert settings.cache_enabled is False


# Spec: "Service configuration sources, in order of precedence: ... 3. Direct
# environment variables"
# Context: the same setting in both sources; the later source in the list wins
# (T47).
def test_environment_overrides_the_config_file(tmp_path):
    environ = config_file(tmp_path, "MAX_SOURCE_SIZE=10\nREQUIRE_TLS=false\n")
    settings = load_settings({**environ, "MAX_SOURCE_SIZE": "99", "REQUIRE_TLS": "on"})
    assert settings.max_source_size == 99
    assert settings.require_tls is True


# Spec: "1. Built-in defaults 2. `DATAGATE_CONFIG` file 3. Direct environment
# variables"
# Context: the three layers together — a setting each source alone supplies
# keeps that source's value.
def test_the_three_sources_layer(tmp_path):
    environ = config_file(tmp_path, "REQUIRE_TLS=yes\nMAX_SOURCE_SIZE=10\n")
    settings = load_settings({**environ, "MAX_SOURCE_SIZE": "20"})
    assert (settings.cache_enabled, settings.require_tls, settings.max_source_size) == (
        True,
        True,
        20,
    )


# Spec: "3. Direct environment variables"
# Context: no config file named at all; the environment alone configures.
def test_environment_alone_configures():
    assert load_settings({"CACHE_ENABLED": "no"}).cache_enabled is False


# Spec: "The config file is `KEY=VALUE` lines"
# Context: whitespace around the key and the value is not part of either (T51).
def test_keys_and_values_are_trimmed(tmp_path):
    environ = config_file(tmp_path, "  MAX_SOURCE_SIZE = 64  \n\tSTORAGE_DIR\t=\t/tmp/d \n")
    settings = load_settings(environ)
    assert settings.max_source_size == 64
    assert settings.storage_dir == "/tmp/d"


# Spec: "The config file is `KEY=VALUE` lines"
# Context: a value containing `=` keeps everything after the first separator.
def test_only_the_first_equals_separates(tmp_path):
    environ = config_file(tmp_path, "STORAGE_DIR=/tmp/a=b\n")
    assert load_settings(environ).storage_dir == "/tmp/a=b"


# Spec: "The config file is `KEY=VALUE` lines"
# Context: values are literal text; no shell-style quote stripping (T52).
def test_quotes_are_part_of_the_value(tmp_path):
    environ = config_file(tmp_path, 'STORAGE_DIR="/tmp/quoted"\n')
    assert load_settings(environ).storage_dir == '"/tmp/quoted"'


# Spec: "with commas for list values"
# Context: several domain suffixes on one `ORIGIN_ALLOWLIST` line.
def test_commas_separate_list_values(tmp_path):
    environ = config_file(tmp_path, "ORIGIN_ALLOWLIST=a.example.com,b.test\n")
    assert load_settings(environ).origin_allowlist == ("a.example.com", "b.test")


# Spec: "with commas for list values"
# Context: padded entries and a trailing comma in the natural spelling (T71).
def test_list_entries_are_trimmed_and_empties_dropped(tmp_path):
    environ = config_file(tmp_path, "ORIGIN_ALLOWLIST= a.test , b.test ,\n")
    assert load_settings(environ).origin_allowlist == ("a.test", "b.test")


# Spec: "with commas for list values" / "3. Direct environment variables"
# Context: a list supplied by the environment uses the same syntax (T71).
def test_list_syntax_is_the_same_in_the_environment():
    assert load_settings({"ORIGIN_ALLOWLIST": "a.test,b.test"}).origin_allowlist == (
        "a.test",
        "b.test",
    )


# Spec: "blank/comment lines ignored"
# Context: empty lines, whitespace-only lines and `#` comments between settings.
def test_blank_and_comment_lines_are_ignored(tmp_path):
    environ = config_file(
        tmp_path,
        "# datagate configuration\n"
        "\n"
        "   \n"
        "REQUIRE_TLS=true\n"
        "  # indented comment\n"
        "\n",
    )
    assert load_settings(environ).require_tls is True


# Spec: "blank/comment lines ignored"
# Context: `#` only starts a comment at the start of a line, so a value keeps
# its own `#` (T50).
def test_a_hash_inside_a_value_is_not_a_comment(tmp_path):
    environ = config_file(tmp_path, "STORAGE_DIR=/tmp/d # notes\n")
    assert load_settings(environ).storage_dir == "/tmp/d # notes"


# Spec: "Invalid config or read failure at startup returns an error and exits."
# Context: a line that is not `KEY=VALUE` and is neither blank nor a comment
# (T49).
@pytest.mark.parametrize("line", ["REQUIRE_TLS", "=true", "   =  ", "just some text"])
def test_a_malformed_line_is_invalid_config(tmp_path, line):
    with pytest.raises(ConfigError):
        load_settings(config_file(tmp_path, f"{line}\n"))


# Spec: "Invalid config or read failure at startup returns an error and exits."
# Context: a well-formed line naming something this service does not configure
# is passed over rather than treated as corruption (T49).
def test_unknown_keys_are_ignored(tmp_path):
    environ = config_file(tmp_path, "LOG_LEVEL=info\nREQUIRE_TLS=on\n")
    assert load_settings(environ).require_tls is True


# Spec: "Invalid config or read failure at startup returns an error and exits."
# Context: `DATAGATE_CONFIG` naming a file that is not there (T48).
def test_a_missing_config_file_is_a_read_failure(tmp_path):
    with pytest.raises(ConfigError):
        load_settings({"DATAGATE_CONFIG": str(tmp_path / "absent.conf")})


# Spec: "Invalid config or read failure at startup returns an error and exits."
# Context: `DATAGATE_CONFIG` naming a directory instead of a file (T48).
def test_an_unreadable_config_path_is_a_read_failure(tmp_path):
    with pytest.raises(ConfigError):
        load_settings({"DATAGATE_CONFIG": str(tmp_path)})


# Spec: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`
# (case-insensitive, trimmed)."
# Context: every accepted true spelling, for each boolean setting.
@pytest.mark.parametrize("name", BOOLEAN_SETTINGS)
@pytest.mark.parametrize("value", TRUE_VALUES)
def test_true_spellings(name, value):
    assert getattr(load_settings({name: value}), name.lower()) is True


# Spec: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`"
# Context: every accepted false spelling, for each boolean setting.
@pytest.mark.parametrize("name", BOOLEAN_SETTINGS)
@pytest.mark.parametrize("value", FALSE_VALUES)
def test_false_spellings(name, value):
    assert getattr(load_settings({name: value}), name.lower()) is False


# Spec: "(case-insensitive, trimmed)"
# Context: mixed case and surrounding whitespace on a boolean value (T38).
@pytest.mark.parametrize("value", ["TRUE", "Yes", " on ", "\tTrue\n"])
def test_booleans_are_case_insensitive_and_trimmed(value):
    assert load_settings({"REQUIRE_TLS": value}).require_tls is True


# Spec: "Boolean values are strict" / "Invalid config ... returns an error"
# Context: values outside the two accepted sets, including an empty one (T53).
@pytest.mark.parametrize("value", ["maybe", "2", "", "y", "enabled", "-1", "truthy"])
def test_invalid_booleans_are_config_errors(value):
    with pytest.raises(ConfigError):
        load_settings({"REQUIRE_TLS": value})


# Spec: "| `MAX_SOURCE_SIZE` | integer bytes | unset |"
# Context: a plain decimal byte count.
def test_max_source_size_is_an_integer():
    assert load_settings({"MAX_SOURCE_SIZE": "1024"}).max_source_size == 1024


# Spec: "| `MAX_SOURCE_SIZE` | integer bytes |"
# Context: spellings that are not an integer number of bytes (T54).
@pytest.mark.parametrize("value", ["10KB", "-1", "1.5", "1_000", "1e3", "", " ", "lots"])
def test_invalid_max_source_size_is_a_config_error(value):
    with pytest.raises(ConfigError):
        load_settings({"MAX_SOURCE_SIZE": value})


# Spec: "| `MAX_SOURCE_SIZE` | integer bytes | unset |"
# Context: zero is a configured limit of zero bytes, not a spelling of unset
# (T54).
def test_zero_is_a_real_limit():
    assert load_settings({"MAX_SOURCE_SIZE": "0"}).max_source_size == 0


# Spec: "| `ORIGIN_ALLOWLIST` | list of domain suffixes | unset |"
# Context: a configured value with no entries is indistinguishable from no
# allowlist (T53).
def test_an_empty_allowlist_is_no_allowlist():
    assert load_settings({"ORIGIN_ALLOWLIST": ""}).origin_allowlist == ()


# Spec: "| `STORAGE_DIR` | path |"
# Context: a setting whose type an empty value cannot meet (T53).
def test_an_empty_storage_dir_is_a_config_error():
    with pytest.raises(ConfigError):
        load_settings({"STORAGE_DIR": "  "})


# Spec: "Invalid config or read failure at startup returns an error and exits."
# Context: the CLI turns the refusal into a non-zero exit without serving (T45).
def test_invalid_config_stops_the_cli(monkeypatch):
    import datagate

    monkeypatch.setenv("MAX_SOURCE_SIZE", "huge")
    monkeypatch.setattr("flask.Flask.run", lambda *args, **kwargs: pytest.fail("served"))
    with pytest.raises(SystemExit) as exit_info:
        datagate.main(["start"])
    assert exit_info.value.code != 0


# Spec: "Invalid config ... at startup"
# Context: settings are resolved once when the app is built, so changing the
# environment afterwards does not change a running app (T70).
def test_settings_are_read_once_at_startup(monkeypatch, client, upload):
    monkeypatch.setenv("MAX_SOURCE_SIZE", "1")
    assert upload("name,age\nada,36\n").status_code == 200
