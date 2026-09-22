"""Spec section: Configuration sources, config file format, and startup failure.

Settings are never read back directly: each one is observed through the behaviour it
controls (endpoint shape for `REQUIRE_TLS`, a 400 for `MAX_SOURCE_SIZE`, a 403 for
`ORIGIN_ALLOWLIST`, origin hit counts for `CACHE_ENABLED`, files on disk for
`STORAGE_DIR`) - which is the only thing the spec actually promises.
"""
import os
import urllib.parse

import pytest

import datagate
from conftest import (assert_error_envelope, assert_startup_failure, spawn_server,
                      stop_server, unused_port, wait_for_server)

CSV = "name,qty\nwidget,3\n"

TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


def convert(client, url, headers=None):
    query = "source=" + urllib.parse.quote(url, safe="")
    return client.get("/convert", query_string=query, headers=headers or {})


def endpoint(client, url):
    response = convert(client, url)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["endpoint"]


# =============================================================================
# Phrase: "Service configuration sources, in order of precedence: 1. Built-in
#          defaults"
# Context: with nothing configured at all, every setting falls back to its
#          documented default (REQUIRE_TLS false, no limit, no allowlist,
#          caching on).
# =============================================================================

def test_no_configuration_at_all_uses_the_defaults(make_app, origin):
    client = make_app().test_client()
    url = origin.add(CSV)
    before = origin.hits(url)
    # REQUIRE_TLS defaults to false -> relative endpoint.
    assert endpoint(client, url) == "/datasets/%s" % datagate.dataset_id(url)
    # No allowlist -> a request without any Referer is fine.
    assert convert(client, url).status_code == 200
    # CACHE_ENABLED defaults to true -> the second convert did not re-download.
    assert origin.hits(url) - before == 1


def test_defaults_impose_no_size_limit(make_app, origin):
    """`MAX_SOURCE_SIZE` is unset by default, and unset means no max."""
    client = make_app().test_client()
    url = origin.add("a,b\n" + "x,y\n" * 20000)
    assert convert(client, url).status_code == 200


# =============================================================================
# Phrase: "2. `DATAGATE_CONFIG` file" (beats the built-in defaults)
# Context: a setting named only in the config file takes effect.
# =============================================================================

def test_config_file_overrides_a_built_in_default(make_app, write_config, origin):
    path = write_config("REQUIRE_TLS=true\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    url = origin.add(CSV)
    assert endpoint(client, url).startswith("https://")


def test_config_file_can_set_every_setting(make_app, write_config, origin, tmp_path):
    storage = tmp_path / "from-file"
    path = write_config(
        "MAX_SOURCE_SIZE=10\n"
        "ORIGIN_ALLOWLIST=example.com\n"
        "REQUIRE_TLS=1\n"
        "STORAGE_DIR=%s\n"
        "CACHE_ENABLED=off\n" % storage
    )
    client = make_app(DATAGATE_CONFIG=path).test_client()
    assert storage.is_dir()
    # The allowlist is live, so every probe below must carry a good Referer.
    good = {"Referer": "https://example.com/page"}
    assert client.get("/datasets/nope").status_code == 403
    url = origin.add(CSV)  # 16 bytes > the 10-byte limit
    response = client.get("/convert", query_string={"source": url}, headers=good)
    assert_error_envelope(response, 400)


def test_settings_absent_from_the_config_file_keep_their_defaults(
        make_app, write_config, origin):
    """A file that sets one key must not disturb the other four."""
    path = write_config("MAX_SOURCE_SIZE=1000000\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    url = origin.add(CSV)
    assert endpoint(client, url) == "/datasets/%s" % datagate.dataset_id(url)
    assert convert(client, url).status_code == 200


def test_unset_config_variable_is_not_an_error(make_app, origin):
    client = make_app().test_client()
    assert convert(client, origin.add(CSV)).status_code == 200


# =============================================================================
# Phrase: "3. Direct environment variables" (highest precedence)
# Context: an environment variable wins over the same key in the config file.
# =============================================================================

def test_environment_variable_overrides_the_config_file(make_app, write_config, origin):
    path = write_config("REQUIRE_TLS=true\n")
    client = make_app(DATAGATE_CONFIG=path, REQUIRE_TLS="false").test_client()
    url = origin.add(CSV)
    assert endpoint(client, url) == "/datasets/%s" % datagate.dataset_id(url)


def test_environment_overrides_only_the_keys_it_names(make_app, write_config, origin):
    path = write_config("REQUIRE_TLS=true\nCACHE_ENABLED=false\n")
    client = make_app(DATAGATE_CONFIG=path, CACHE_ENABLED="true").test_client()
    url = origin.add(CSV)
    before = origin.hits(url)
    # CACHE_ENABLED came from the environment...
    assert endpoint(client, url).startswith("https://")  # ...REQUIRE_TLS from the file
    convert(client, url)
    assert origin.hits(url) - before == 1


def test_environment_max_source_size_overrides_the_file(make_app, write_config, origin):
    path = write_config("MAX_SOURCE_SIZE=1\n")
    client = make_app(DATAGATE_CONFIG=path, MAX_SOURCE_SIZE="1000000").test_client()
    assert convert(client, origin.add(CSV)).status_code == 200


def test_environment_allowlist_overrides_the_file(make_app, write_config, origin):
    path = write_config("ORIGIN_ALLOWLIST=example.com\n")
    client = make_app(DATAGATE_CONFIG=path, ORIGIN_ALLOWLIST="other.test").test_client()
    assert convert(client, origin.add(CSV),
                   {"Referer": "https://example.com/p"}).status_code == 403
    assert convert(client, origin.add(CSV),
                   {"Referer": "https://other.test/p"}).status_code == 200


def test_empty_environment_value_clears_a_file_allowlist(make_app, write_config, origin):
    """An empty list value is "set to nothing", not "unset" (AMBIGUITIES T67)."""
    path = write_config("ORIGIN_ALLOWLIST=example.com\n")
    client = make_app(DATAGATE_CONFIG=path, ORIGIN_ALLOWLIST="").test_client()
    assert convert(client, origin.add(CSV)).status_code == 200


# =============================================================================
# Phrase: "The config file is `KEY=VALUE` lines"
# Context: the basic grammar - one setting per line, split at the first `=`.
# =============================================================================

def test_key_value_lines_are_read(make_app, write_config, origin):
    path = write_config("CACHE_ENABLED=false\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    url = origin.add(CSV)
    before = origin.hits(url)
    convert(client, url)
    convert(client, url)
    assert origin.hits(url) - before == 2


def test_surrounding_whitespace_around_key_and_value_is_ignored(
        make_app, write_config, origin):
    path = write_config("   REQUIRE_TLS  =  true   \n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    assert endpoint(client, origin.add(CSV)).startswith("https://")


def test_a_later_line_wins_over_an_earlier_one_for_the_same_key(
        make_app, write_config, origin):
    path = write_config("REQUIRE_TLS=true\nREQUIRE_TLS=false\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    url = origin.add(CSV)
    assert endpoint(client, url) == "/datasets/%s" % datagate.dataset_id(url)


def test_a_value_may_contain_an_equals_sign(make_app, write_config, tmp_path):
    """Only the first `=` separates; the rest belongs to the value."""
    storage = tmp_path / "dir=with=equals"
    path = write_config("STORAGE_DIR=%s\n" % storage)
    make_app(DATAGATE_CONFIG=path)
    assert storage.is_dir()


def test_unknown_keys_are_ignored(make_app, write_config, origin):
    """A key outside the settings table is not "invalid config" (T66)."""
    path = write_config("SOMETHING_ELSE=whatever\nREQUIRE_TLS=true\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    assert endpoint(client, origin.add(CSV)).startswith("https://")


def test_keys_are_case_sensitive(make_app, write_config, origin):
    """`require_tls` is not `REQUIRE_TLS`; it is simply an unknown key."""
    path = write_config("require_tls=true\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    url = origin.add(CSV)
    assert endpoint(client, url) == "/datasets/%s" % datagate.dataset_id(url)


# =============================================================================
# Phrase: "with commas for list values"
# Context: ORIGIN_ALLOWLIST is the one list-typed setting.
# =============================================================================

def test_comma_separated_list_value(make_app, write_config, origin):
    path = write_config("ORIGIN_ALLOWLIST=a.test,b.test,c.test\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    for host in ("a.test", "b.test", "c.test"):
        assert convert(client, origin.add(CSV),
                       {"Referer": "https://%s/p" % host}).status_code == 200
    assert convert(client, origin.add(CSV),
                   {"Referer": "https://d.test/p"}).status_code == 403


def test_list_entries_are_trimmed_and_empty_entries_dropped(
        make_app, write_config, origin):
    path = write_config("ORIGIN_ALLOWLIST= a.test , , b.test ,\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    for host in ("a.test", "b.test"):
        assert convert(client, origin.add(CSV),
                       {"Referer": "https://%s/p" % host}).status_code == 200
    assert convert(client, origin.add(CSV),
                   {"Referer": "https://z.test/p"}).status_code == 403


def test_single_element_list_needs_no_comma(make_app, write_config, origin):
    path = write_config("ORIGIN_ALLOWLIST=only.test\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    assert convert(client, origin.add(CSV),
                   {"Referer": "https://only.test/p"}).status_code == 200


def test_environment_list_values_use_commas_too(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="a.test,b.test").test_client()
    assert convert(client, origin.add(CSV),
                   {"Referer": "https://b.test/p"}).status_code == 200


# =============================================================================
# Phrase: "blank/comment lines ignored"
# Context: a file may be commented and spaced out freely.
# =============================================================================

def test_blank_and_whitespace_only_lines_are_ignored(make_app, write_config, origin):
    path = write_config("\n\n   \n\t\nREQUIRE_TLS=true\n\n   \n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    assert endpoint(client, origin.add(CSV)).startswith("https://")


def test_comment_lines_are_ignored(make_app, write_config, origin):
    path = write_config("# datagate config\n#REQUIRE_TLS=false\nREQUIRE_TLS=true\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    assert endpoint(client, origin.add(CSV)).startswith("https://")


def test_indented_comment_lines_are_ignored(make_app, write_config, origin):
    path = write_config("    # indented comment\nREQUIRE_TLS=true\n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    assert endpoint(client, origin.add(CSV)).startswith("https://")


def test_an_entirely_blank_or_commented_file_configures_nothing(
        make_app, write_config, origin):
    path = write_config("# nothing here\n\n   \n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    url = origin.add(CSV)
    assert endpoint(client, url) == "/datasets/%s" % datagate.dataset_id(url)


def test_an_empty_file_configures_nothing(make_app, write_config, origin):
    client = make_app(DATAGATE_CONFIG=write_config("")).test_client()
    assert convert(client, origin.add(CSV)).status_code == 200


def test_a_file_without_a_trailing_newline_is_read(make_app, write_config, origin):
    client = make_app(DATAGATE_CONFIG=write_config("REQUIRE_TLS=true")).test_client()
    assert endpoint(client, origin.add(CSV)).startswith("https://")


# =============================================================================
# Phrase: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`
#          (case-insensitive, trimmed)."
# Context: applies to every boolean setting - REQUIRE_TLS and CACHE_ENABLED.
# =============================================================================

@pytest.mark.parametrize("value", TRUE_VALUES + ("TRUE", "Yes", "ON", "oN"))
def test_require_tls_true_spellings(make_app, origin, value):
    client = make_app(REQUIRE_TLS=value).test_client()
    assert endpoint(client, origin.add(CSV)).startswith("https://")


@pytest.mark.parametrize("value", FALSE_VALUES + ("FALSE", "No", "OFF", "oFf"))
def test_require_tls_false_spellings(make_app, origin, value):
    client = make_app(REQUIRE_TLS=value).test_client()
    url = origin.add(CSV)
    assert endpoint(client, url) == "/datasets/%s" % datagate.dataset_id(url)


@pytest.mark.parametrize("value", [" true", "true ", "  ON  ", "\ttrue\n", " 0 "])
def test_boolean_values_are_trimmed(make_app, origin, value):
    """Padding is now explicitly forgiven (AMBIGUITIES T58, updated)."""
    client = make_app(REQUIRE_TLS=value).test_client()
    expected = value.strip().lower() in TRUE_VALUES
    assert endpoint(client, origin.add(CSV)).startswith("https://") is expected


@pytest.mark.parametrize("value", [" on ", "TRUE ", " off"])
def test_padded_cache_enabled_is_accepted(make_app, origin, value):
    client = make_app(CACHE_ENABLED=value).test_client()
    url = origin.add(CSV)
    before = origin.hits(url)
    convert(client, url)
    convert(client, url)
    expected = 1 if value.strip().lower() in TRUE_VALUES else 2
    assert origin.hits(url) - before == expected


def test_booleans_are_read_from_the_config_file_with_the_same_rules(
        make_app, write_config, origin):
    path = write_config("REQUIRE_TLS=  YeS  \n")
    client = make_app(DATAGATE_CONFIG=path).test_client()
    assert endpoint(client, origin.add(CSV)).startswith("https://")


# =============================================================================
# Phrase: "Invalid config ... at startup returns an error and exits."
# Context: a bad value for any setting stops the process before it binds.
# =============================================================================

@pytest.mark.parametrize("value", ["maybe", "2", "-1", "t", "", "   ", "yes no", "1.0"])
def test_invalid_require_tls_fails_startup(value):
    assert_startup_failure({"REQUIRE_TLS": value})


def test_invalid_require_tls_names_the_setting():
    log = assert_startup_failure({"REQUIRE_TLS": "maybe"})
    assert "REQUIRE_TLS" in log


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "10MB", "1_000", "0x10", "1e3"])
def test_invalid_max_source_size_fails_startup(value):
    assert_startup_failure({"MAX_SOURCE_SIZE": value})


def test_invalid_max_source_size_names_the_setting():
    log = assert_startup_failure({"MAX_SOURCE_SIZE": "huge"})
    assert "MAX_SOURCE_SIZE" in log


def test_invalid_value_in_the_config_file_fails_startup(tmp_path):
    path = tmp_path / "bad.conf"
    path.write_text("REQUIRE_TLS=sometimes\n")
    assert_startup_failure({"DATAGATE_CONFIG": str(path)})


def test_a_line_that_is_not_key_value_fails_startup(tmp_path):
    """Neither blank, nor a comment, nor `KEY=VALUE` - so, invalid config (T66)."""
    path = tmp_path / "junk.conf"
    path.write_text("REQUIRE_TLS=true\nthis is not a setting\n")
    assert_startup_failure({"DATAGATE_CONFIG": str(path)})


def test_a_line_with_an_empty_key_fails_startup(tmp_path):
    path = tmp_path / "nokey.conf"
    path.write_text("=true\n")
    assert_startup_failure({"DATAGATE_CONFIG": str(path)})


def test_invalid_config_in_the_file_is_still_invalid_when_the_environment_agrees(
        tmp_path):
    """The file is parsed and validated even for a key the environment overrides."""
    path = tmp_path / "bad2.conf"
    path.write_text("MAX_SOURCE_SIZE=enormous\n")
    assert_startup_failure({"DATAGATE_CONFIG": str(path), "MAX_SOURCE_SIZE": "10"})


# =============================================================================
# Phrase: "... or read failure at startup returns an error and exits."
# Context: DATAGATE_CONFIG naming something unreadable is fatal (T65).
# =============================================================================

def test_missing_config_file_fails_startup(tmp_path):
    assert_startup_failure({"DATAGATE_CONFIG": str(tmp_path / "nope.conf")})


def test_config_path_that_is_a_directory_fails_startup(tmp_path):
    directory = tmp_path / "adir"
    directory.mkdir()
    assert_startup_failure({"DATAGATE_CONFIG": str(directory)})


def test_unreadable_config_file_fails_startup(tmp_path):
    path = tmp_path / "locked.conf"
    path.write_text("REQUIRE_TLS=true\n")
    os.chmod(path, 0o000)
    if os.access(str(path), os.R_OK):  # running as root: the mode proves nothing
        pytest.skip("cannot make a file unreadable as this user")
    try:
        assert_startup_failure({"DATAGATE_CONFIG": str(path)})
    finally:
        os.chmod(path, 0o600)


def test_read_failure_message_names_the_config(tmp_path):
    log = assert_startup_failure({"DATAGATE_CONFIG": str(tmp_path / "absent.conf")})
    assert "absent.conf" in log or "DATAGATE_CONFIG" in log


# =============================================================================
# Phrase: "Invalid config ... exits" - and, conversely, valid config starts.
# Context: the whole configuration path works in the real `start` process.
# =============================================================================

def test_valid_configuration_starts_the_server(tmp_path):
    path = tmp_path / "ok.conf"
    path.write_text(
        "# a real config\n\nREQUIRE_TLS=false\nMAX_SOURCE_SIZE=1048576\n"
        "ORIGIN_ALLOWLIST=\nSTORAGE_DIR=%s\n" % (tmp_path / "store")
    )
    port = unused_port()
    proc = spawn_server(["start", "--port", str(port)],
                        {"DATAGATE_CONFIG": str(path)})
    try:
        status, payload = wait_for_server(
            "http://127.0.0.1:%d/datasets/nope" % port, proc)
        assert status == 404
        assert payload["ok"] is False
        assert (tmp_path / "store").is_dir()
    finally:
        stop_server(proc)
