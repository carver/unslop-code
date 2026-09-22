"""Spec section: service configuration sources, parsing, and startup failure."""


import pytest

from conftest import (
    assert_error_envelope,
    convert_ok,
    free_port,
    port_is_closed,
    start_expecting_failure,
    write_config,
)

A = "city,pop\nOslo,700000\nLima,9000000\n"


def endpoint_of(gate, origin, path, body=A):
    url = origin.add(path, body)
    return convert_ok(gate, url)


# ---------------------------------------------------------------------------
# Phrase: "Service configuration sources, in order of precedence:
#          1. Built-in defaults"
# Context: nothing configured at all -- every documented default is in force.
# ---------------------------------------------------------------------------
def test_built_in_defaults_apply_when_nothing_is_configured(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1")
    # REQUIRE_TLS default false -> relative endpoint.
    endpoint = endpoint_of(gate, origin, "/cfg-defaults.csv")
    assert endpoint.startswith("/datasets/")
    # ORIGIN_ALLOWLIST unset -> a request with no Referer is routed normally.
    assert gate.get(endpoint).status_code == 200


# ---------------------------------------------------------------------------
# Phrase: "2. `DATAGATE_CONFIG` file"
# Context: a setting read from the config file beats the built-in default.
# ---------------------------------------------------------------------------
def test_config_file_overrides_built_in_default(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "REQUIRE_TLS=true\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    endpoint = endpoint_of(gate, origin, "/cfg-file-wins.csv")
    assert endpoint.startswith("https://")


# ---------------------------------------------------------------------------
# Phrase: "3. Direct environment variables" (highest precedence)
# Context: the same key set in both the config file and the environment.
# ---------------------------------------------------------------------------
def test_environment_variable_overrides_config_file(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "REQUIRE_TLS=true\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg, "REQUIRE_TLS": "false"})
    endpoint = endpoint_of(gate, origin, "/cfg-env-wins.csv")
    assert endpoint.startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "3. Direct environment variables" (highest precedence), reversed
# Context: the file says false, the environment says true.
# ---------------------------------------------------------------------------
def test_environment_variable_overrides_config_file_reversed(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "REQUIRE_TLS=false\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg, "REQUIRE_TLS": "on"})
    endpoint = endpoint_of(gate, origin, "/cfg-env-wins-2.csv")
    assert endpoint.startswith("https://")


# ---------------------------------------------------------------------------
# Phrase: "The config file is `KEY=VALUE` lines"
# Context: several unrelated settings in one file, each taking effect.
# ---------------------------------------------------------------------------
def test_config_file_is_key_equals_value_lines(fresh_gate, origin, tmp_path):
    cfg = write_config(
        tmp_path,
        "REQUIRE_TLS=true\nMAX_SOURCE_SIZE=10\nCACHE_ENABLED=false\n",
    )
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    url = origin.add("/cfg-multi.csv", "a,b\n1,2\n")  # 8 bytes, under the limit
    resp = gate.convert(source=url)
    assert resp.status_code == 200, resp.text
    assert resp.json()["endpoint"].startswith("https://")
    # MAX_SOURCE_SIZE from the same file is enforced.
    big = origin.add("/cfg-multi-big.csv", "a,b\n1,2\n3,4\n")
    assert_error_envelope(gate.convert(source=big), 400)


# ---------------------------------------------------------------------------
# Phrase: "with commas for list values"
# Context: ORIGIN_ALLOWLIST is the only list-typed setting.
# ---------------------------------------------------------------------------
def test_config_file_splits_list_values_on_commas(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "ORIGIN_ALLOWLIST=alpha.test,beta.test\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    for host in ("alpha.test", "beta.test"):
        resp = gate.get("/datasets/nope", headers={"Referer": f"http://{host}/p"})
        assert resp.status_code == 404, resp.text
    resp = gate.get("/datasets/nope", headers={"Referer": "http://gamma.test/p"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Phrase: "with commas for list values"
# Context: whitespace around the commas is not part of a domain suffix.
# ---------------------------------------------------------------------------
def test_list_values_tolerate_whitespace_around_commas(fresh_gate, tmp_path):
    cfg = write_config(tmp_path, "ORIGIN_ALLOWLIST = alpha.test , beta.test \n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    assert gate.get("/datasets/nope",
                    headers={"Referer": "http://beta.test/p"}).status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "blank/comment lines ignored"
# Context: a file that is mostly blank lines and comments still parses.
# ---------------------------------------------------------------------------
def test_blank_and_comment_lines_are_ignored(fresh_gate, origin, tmp_path):
    cfg = write_config(
        tmp_path,
        "# datagate configuration\n"
        "\n"
        "   \n"
        "REQUIRE_TLS=true\n"
        "   # indented comment = not a KEY=VALUE line\n"
        "\n",
    )
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    endpoint = endpoint_of(gate, origin, "/cfg-comments.csv")
    assert endpoint.startswith("https://")


# ---------------------------------------------------------------------------
# Phrase: "Invalid config or read failure at startup returns an error and exits."
# Context: DATAGATE_CONFIG names a file that does not exist.
# ---------------------------------------------------------------------------
def test_missing_config_file_is_a_startup_failure(tmp_path):
    missing = str(tmp_path / "absent.conf")
    code, log, port = start_expecting_failure(env={"DATAGATE_CONFIG": missing})
    assert code != 0
    assert "absent.conf" in log or "DATAGATE_CONFIG" in log
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "... or read failure at startup ..."
# Context: DATAGATE_CONFIG names a directory, which cannot be read as a file.
# ---------------------------------------------------------------------------
def test_unreadable_config_file_is_a_startup_failure(tmp_path):
    directory = tmp_path / "conf.d"
    directory.mkdir()
    code, log, port = start_expecting_failure(env={"DATAGATE_CONFIG": str(directory)})
    assert code != 0
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "Invalid config ... returns an error and exits."
# Context: a line that is not KEY=VALUE, not blank, and not a comment.
# ---------------------------------------------------------------------------
def test_malformed_config_line_is_a_startup_failure(tmp_path):
    cfg = write_config(tmp_path, "REQUIRE_TLS=true\nthis is not a setting\n")
    code, log, port = start_expecting_failure(env={"DATAGATE_CONFIG": cfg})
    assert code != 0
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "Invalid config ... returns an error and exits."
# Context: a KEY=VALUE line whose key is empty.
# ---------------------------------------------------------------------------
def test_empty_key_is_a_startup_failure(tmp_path):
    cfg = write_config(tmp_path, "=true\n")
    code, _log, port = start_expecting_failure(env={"DATAGATE_CONFIG": cfg})
    assert code != 0
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "Invalid config ... returns an error and exits."
# Context: a value that is not valid for its documented type (integer).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["abc", "1.5", "-1", "1_000", "10KB", "0x10", " "])
def test_invalid_max_source_size_is_a_startup_failure(tmp_path, value):
    cfg = write_config(tmp_path, f"MAX_SOURCE_SIZE={value}\n")
    code, log, port = start_expecting_failure(env={"DATAGATE_CONFIG": cfg})
    assert code != 0
    assert "MAX_SOURCE_SIZE" in log
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "Invalid config ... returns an error and exits."
# Context: the same invalid integer supplied directly in the environment.
# ---------------------------------------------------------------------------
def test_invalid_max_source_size_from_environment_is_a_startup_failure():
    code, log, port = start_expecting_failure(env={"MAX_SOURCE_SIZE": "lots"})
    assert code != 0
    assert "MAX_SOURCE_SIZE" in log
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "`MAX_SOURCE_SIZE` | integer bytes | unset"
# Context: a plain non-negative integer is accepted, including zero.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["0", "1", "1024", "  2048  "])
def test_valid_max_source_size_values_start(fresh_gate, value):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": value})
    assert gate.get("/datasets/nope").status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`"
# Context: every accepted true spelling of REQUIRE_TLS.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_boolean_true_spellings(fresh_gate, origin, value):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": value})
    endpoint = endpoint_of(gate, origin, f"/cfg-bool-t-{value}.csv")
    assert endpoint.startswith("https://")


# ---------------------------------------------------------------------------
# Phrase: "Boolean values are strict: ... `0/false/no/off`"
# Context: every accepted false spelling of REQUIRE_TLS.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_boolean_false_spellings(fresh_gate, origin, value):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": value})
    endpoint = endpoint_of(gate, origin, f"/cfg-bool-f-{value}.csv")
    assert endpoint.startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "(case-insensitive, trimmed)"
# Context: mixed case with surrounding whitespace is still a boolean.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["TRUE", "  Yes  ", "On", "\tTrue\t"])
def test_boolean_values_are_case_insensitive_and_trimmed(fresh_gate, origin, value):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": value})
    endpoint = endpoint_of(gate, origin, f"/cfg-bool-ci-{value.strip().lower()}.csv")
    assert endpoint.startswith("https://")


# ---------------------------------------------------------------------------
# Phrase: "Boolean values are strict"
# Context: anything outside the two accepted sets is invalid config.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["truthy", "2", "-1", "y", "n", "enabled", "TRUE!"])
def test_invalid_boolean_is_a_startup_failure(value):
    code, log, port = start_expecting_failure(env={"REQUIRE_TLS": value})
    assert code != 0
    assert "REQUIRE_TLS" in log
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "Boolean values are strict" (the same rule for `CACHE_ENABLED`)
# Context: CACHE_ENABLED is a boolean setting in the same table.
# ---------------------------------------------------------------------------
def test_invalid_cache_enabled_is_a_startup_failure():
    code, log, port = start_expecting_failure(env={"CACHE_ENABLED": "maybe"})
    assert code != 0
    assert "CACHE_ENABLED" in log
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "`CACHE_ENABLED` | boolean | `true`" read from the config file
# Context: CACHE_ENABLED must be settable through the config file too.
# ---------------------------------------------------------------------------
def test_cache_enabled_is_configurable_from_the_config_file(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "CACHE_ENABLED=off\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    path = "/cfg-cache-off.csv"
    url = origin.add(path, A)
    convert_ok(gate, url)
    first = origin.hit_count(path)
    convert_ok(gate, url)
    assert origin.hit_count(path) == first + 1


# ---------------------------------------------------------------------------
# Phrase: "`CACHE_ENABLED` | boolean | `true`" (env beats file)
# Context: precedence applies to every setting, not just REQUIRE_TLS.
# ---------------------------------------------------------------------------
def test_cache_enabled_environment_beats_config_file(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "CACHE_ENABLED=off\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg, "CACHE_ENABLED": "on"})
    path = "/cfg-cache-env-on.csv"
    url = origin.add(path, A)
    convert_ok(gate, url)
    first = origin.hit_count(path)
    convert_ok(gate, url)
    assert origin.hit_count(path) == first  # cached: no second download


# ---------------------------------------------------------------------------
# Phrase: "`CACHE_ENABLED` | boolean | `true`"
# Context: the documented default with no configuration at all.
# ---------------------------------------------------------------------------
def test_cache_enabled_defaults_to_true(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1")
    path = "/cfg-cache-default.csv"
    url = origin.add(path, A)
    convert_ok(gate, url)
    first = origin.hit_count(path)
    convert_ok(gate, url)
    assert origin.hit_count(path) == first


# ---------------------------------------------------------------------------
# Phrase: "The config file is `KEY=VALUE` lines"
# Context: a repeated key -- the last assignment in the file is the one used.
# ---------------------------------------------------------------------------
def test_repeated_key_in_config_file_takes_the_last_value(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "REQUIRE_TLS=false\nREQUIRE_TLS=true\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    endpoint = endpoint_of(gate, origin, "/cfg-dup-key.csv")
    assert endpoint.startswith("https://")


# ---------------------------------------------------------------------------
# Phrase: "The config file is `KEY=VALUE` lines"
# Context: a value containing '=' keeps everything after the first separator.
# ---------------------------------------------------------------------------
def test_only_the_first_equals_separates_key_from_value(fresh_gate, tmp_path):
    cfg = write_config(tmp_path, "ORIGIN_ALLOWLIST=a=b.test\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    assert gate.get("/datasets/nope",
                    headers={"Referer": "http://a=b.test/p"}).status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "`DATAGATE_CONFIG` file"
# Context: DATAGATE_CONFIG unset means there is simply no file layer.
# ---------------------------------------------------------------------------
def test_no_config_file_is_not_an_error(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1")
    assert gate.get("/datasets/nope").status_code == 404
    assert endpoint_of(gate, origin, "/cfg-nofile.csv").startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "`DATAGATE_CONFIG` file"
# Context: an empty config file configures nothing and is not an error.
# ---------------------------------------------------------------------------
def test_empty_config_file_is_not_an_error(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    assert endpoint_of(gate, origin, "/cfg-empty-file.csv").startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "Invalid config ... returns an error and exits."
# Context: a startup failure must not leave a half-configured server listening.
# ---------------------------------------------------------------------------
def test_startup_failure_never_binds_the_port():
    code, _log, port = start_expecting_failure(env={"REQUIRE_TLS": "sometimes"})
    assert code != 0
    assert port_is_closed(port)
