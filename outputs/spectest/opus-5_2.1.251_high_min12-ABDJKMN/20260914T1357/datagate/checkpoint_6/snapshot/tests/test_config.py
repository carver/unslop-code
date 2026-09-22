"""Spec tests for "Configuration" — sources, precedence, file format, types.

Each section quotes the spec phrase it covers.
"""
import os
import urllib.parse

import pytest

from conftest import (assert_startup_failure, running, startup_result,
                      write_config)

SIMPLE = "name,age\nada,36\ngrace,45\n"


def upload_endpoint(client, payload=SIMPLE):
    """POST /upload a small CSV and return the `endpoint` string."""
    status, _, data = client.upload(payload.encode("utf-8"))
    assert status == 200, data
    return data["endpoint"]


def convert_endpoint(client, url, headers=None):
    status, _, data = client.convert(url, headers=headers)
    assert status == 200, data
    return data["endpoint"]


def hits(origin, url):
    return origin.hits.get(urllib.parse.urlsplit(url).path, 0)


@pytest.fixture
def config(tmp_path):
    """Write a DATAGATE_CONFIG file; returns its path."""
    counter = {"n": 0}

    def make(text, name=None):
        counter["n"] += 1
        path = tmp_path / (name or "datagate-%d.conf" % counter["n"])
        return write_config(path, text)
    return make


# ==========================================================================
# Spec: "Service configuration sources, in order of precedence:
#        1. Built-in defaults"
# ==========================================================================
def test_defaults_apply_with_no_configuration(origin, csv_url):
    """Nothing configured: cache on, no TLS URLs, no allowlist, no size cap."""
    env = {"DATAGATE_CONFIG": None, "CACHE_ENABLED": None,
           "MAX_SOURCE_SIZE": None, "ORIGIN_ALLOWLIST": None,
           "REQUIRE_TLS": None, "STORAGE_DIR": None}
    url = csv_url(SIMPLE, name="defaults")
    with running(env, "cfg_defaults") as client:
        # REQUIRE_TLS default false -> relative endpoint.
        endpoint = convert_endpoint(client, url)
        assert endpoint.startswith("/datasets/")
        # ORIGIN_ALLOWLIST unset -> no Referer needed.
        assert client.get(endpoint)[0] == 200
        # CACHE_ENABLED default true -> second convert does not re-download.
        baseline = hits(origin, url)
        assert convert_endpoint(client, url) == endpoint
        assert hits(origin, url) == baseline
        # MAX_SOURCE_SIZE unset -> no maximum.
        big = "a,b\n" + "1,2\n" * 20000
        assert client.upload(big.encode("utf-8"))[0] == 200


# ==========================================================================
# Spec: "2. `DATAGATE_CONFIG` file"
# ==========================================================================
def test_config_file_supplies_settings(config):
    path = config("REQUIRE_TLS=true\n")
    with running({"DATAGATE_CONFIG": path, "REQUIRE_TLS": None},
                 "cfg_file") as client:
        assert upload_endpoint(client).startswith("https://")


def test_config_file_overrides_built_in_default(origin, csv_url, config):
    """The file layer beats the defaults: CACHE_ENABLED defaults to true."""
    path = config("CACHE_ENABLED=off\n")
    url = csv_url(SIMPLE, name="file-beats-default")
    with running({"DATAGATE_CONFIG": path, "CACHE_ENABLED": None},
                 "cfg_file") as client:
        convert_endpoint(client, url)
        baseline = hits(origin, url)
        convert_endpoint(client, url)
        assert hits(origin, url) == baseline + 1  # re-downloaded: cache off


def test_config_file_can_set_every_setting(config, tmp_path):
    store = tmp_path / "store-all"
    path = config(
        "MAX_SOURCE_SIZE=10\n"
        "ORIGIN_ALLOWLIST=allowed.example\n"
        "REQUIRE_TLS=true\n"
        "STORAGE_DIR=%s\n"
        "CACHE_ENABLED=false\n" % store)
    ref = {"Referer": "https://allowed.example/page"}
    with running({"DATAGATE_CONFIG": path}, "cfg_all") as client:
        # Allowlist active: a request without Referer is refused.
        assert client.get("/datasets/nope")[0] == 403
        # Size limit active (the CSV body is well over 10 bytes).
        status, _, data = client.upload(SIMPLE.encode("utf-8"), headers=ref)
        assert status == 400, data
        # REQUIRE_TLS active.
        status, _, data = client.upload(b"a,b\n1,2\n", headers=ref)
        assert status == 200, data
        assert data["endpoint"].startswith("https://")
    assert os.path.isdir(str(store))


# ==========================================================================
# Spec: "3. Direct environment variables"
# ==========================================================================
def test_environment_variable_supplies_settings():
    with running({"REQUIRE_TLS": "true", "DATAGATE_CONFIG": None},
                 "cfg_env") as client:
        assert upload_endpoint(client).startswith("https://")


# Spec: environment variables have the highest precedence.
def test_environment_overrides_config_file(config):
    path = config("REQUIRE_TLS=true\n")
    with running({"DATAGATE_CONFIG": path, "REQUIRE_TLS": "false"},
                 "cfg_env") as client:
        assert upload_endpoint(client).startswith("/datasets/")


# Spec: precedence holds per setting, not per source: a file value survives
# when the environment does not mention that key.
def test_environment_overrides_only_the_keys_it_sets(config, tmp_path):
    store = tmp_path / "store-partial"
    path = config("REQUIRE_TLS=true\nSTORAGE_DIR=%s\n" % store)
    with running({"DATAGATE_CONFIG": path, "REQUIRE_TLS": "no"},
                 "cfg_env") as client:
        assert upload_endpoint(client).startswith("/datasets/")
    assert os.path.isdir(str(store))  # STORAGE_DIR still came from the file


@pytest.mark.parametrize("key,value,probe", [
    ("MAX_SOURCE_SIZE", "5", "size"),
    ("ORIGIN_ALLOWLIST", "env.example", "allowlist"),
])
def test_environment_overrides_file_for_each_setting(config, key, value, probe):
    path = config("%s=\n" % key)  # file clears the setting; env re-sets it
    with running({"DATAGATE_CONFIG": path, key: value}, "cfg_env") as client:
        if probe == "size":
            assert client.upload(SIMPLE.encode("utf-8"))[0] == 400
        else:
            assert client.get("/datasets/x")[0] == 403


# ==========================================================================
# Spec: "The config file is `KEY=VALUE` lines"
# ==========================================================================
def test_config_file_parses_multiple_keys(config):
    path = config("REQUIRE_TLS=on\nMAX_SOURCE_SIZE=4\n")
    with running({"DATAGATE_CONFIG": path}, "cfg_file") as client:
        status, _, data = client.upload(SIMPLE.encode("utf-8"))
        assert status == 400, data
        assert data["ok"] is False


# Spec: "`KEY=VALUE`" — a value containing `=` keeps everything after the first
# separator (only the first `=` splits).
def test_value_may_contain_equals(config, tmp_path):
    store = tmp_path / "eq=dir"
    path = config("STORAGE_DIR=%s\n" % store)
    with running({"DATAGATE_CONFIG": path}, "cfg_file") as client:
        assert client.get("/datasets/unknown")[0] == 404
    assert os.path.isdir(str(store))


# Spec: "`KEY=VALUE` lines" + "Boolean values are ... trimmed" — surrounding
# whitespace around the key and the value is not part of either (AMBIGUITIES T77).
def test_whitespace_around_key_and_value_is_trimmed(config):
    path = config("   REQUIRE_TLS  =   true   \n")
    with running({"DATAGATE_CONFIG": path}, "cfg_file") as client:
        assert upload_endpoint(client).startswith("https://")


# Spec: "The config file is `KEY=VALUE` lines" — a line that is not blank, not
# a comment and has no `=` is invalid config (AMBIGUITIES T78).
@pytest.mark.parametrize("text", [
    "REQUIRE_TLS true\n",
    "REQUIRE_TLS\n",
    "=true\n",
    "   =  true\n",
    "REQUIRE_TLS=true\ngarbage line\n",
])
def test_malformed_line_fails_startup(config, text):
    assert_startup_failure({"DATAGATE_CONFIG": config(text)}, "cfg_bad")


# A well-formed line naming an unknown key is ignored (AMBIGUITIES T79).
def test_unknown_key_is_ignored(config):
    path = config("FUTURE_SETTING=whatever\nREQUIRE_TLS=true\n")
    with running({"DATAGATE_CONFIG": path}, "cfg_file") as client:
        assert upload_endpoint(client).startswith("https://")


# ==========================================================================
# Spec: "with commas for list values"
# ==========================================================================
def test_list_value_splits_on_commas(config):
    path = config("ORIGIN_ALLOWLIST=one.example,two.example\n")
    with running({"DATAGATE_CONFIG": path}, "cfg_list") as client:
        for host in ("one.example", "two.example"):
            headers = {"Referer": "https://%s/p" % host}
            assert client.get("/datasets/x", headers=headers)[0] == 404
        headers = {"Referer": "https://three.example/p"}
        assert client.get("/datasets/x", headers=headers)[0] == 403


# Spec: "with commas for list values" — entries are trimmed (AMBIGUITIES T77).
def test_list_entries_are_trimmed(config):
    path = config("ORIGIN_ALLOWLIST= one.example , two.example \n")
    with running({"DATAGATE_CONFIG": path}, "cfg_list") as client:
        for host in ("one.example", "two.example"):
            headers = {"Referer": "https://%s/p" % host}
            assert client.get("/datasets/x", headers=headers)[0] == 404


# A single value is a one-entry list.
def test_single_entry_list(config):
    path = config("ORIGIN_ALLOWLIST=solo.example\n")
    with running({"DATAGATE_CONFIG": path}, "cfg_list") as client:
        headers = {"Referer": "https://solo.example/p"}
        assert client.get("/datasets/x", headers=headers)[0] == 404
        assert client.get("/datasets/x")[0] == 403


# Empty pieces between commas are dropped (AMBIGUITIES T88).
def test_empty_list_entries_are_dropped(config):
    path = config("ORIGIN_ALLOWLIST=a.example,,b.example,\n")
    with running({"DATAGATE_CONFIG": path}, "cfg_list") as client:
        assert client.get("/datasets/x",
                          headers={"Referer": "https://b.example/"})[0] == 404
        # An empty entry must not become a suffix that matches everything.
        assert client.get("/datasets/x",
                          headers={"Referer": "https://other.test/"})[0] == 403


# ==========================================================================
# Spec: "blank/comment lines ignored"
# ==========================================================================
def test_blank_and_comment_lines_are_ignored(config):
    path = config(
        "# datagate configuration\n"
        "\n"
        "   \n"
        "REQUIRE_TLS=true\n"
        "\t\n"
        "   # indented comment\n"
        "\n")
    with running({"DATAGATE_CONFIG": path}, "cfg_file") as client:
        assert upload_endpoint(client).startswith("https://")


# A file that is entirely blank/comments leaves every default in place.
def test_config_file_of_only_comments_keeps_defaults(config):
    path = config("# nothing here\n\n#    \n")
    with running({"DATAGATE_CONFIG": path, "REQUIRE_TLS": None},
                 "cfg_file") as client:
        assert upload_endpoint(client).startswith("/datasets/")


# An empty file is valid.
def test_empty_config_file_is_valid(config):
    with running({"DATAGATE_CONFIG": config("")}, "cfg_file") as client:
        assert client.get("/datasets/unknown")[0] == 404


# A comment marker is only honoured at the start of a line; `#` inside a value
# is ordinary text, so this boolean is invalid (AMBIGUITIES T76).
def test_inline_hash_is_not_a_comment(config):
    assert_startup_failure({"DATAGATE_CONFIG": config("REQUIRE_TLS=true # yes\n")},
                           "cfg_bad")


# ==========================================================================
# Spec: "Invalid config or read failure at startup returns an error and exits."
# ==========================================================================
@pytest.mark.parametrize("text", [
    "REQUIRE_TLS=maybe\n",
    "CACHE_ENABLED=sometimes\n",
    "MAX_SOURCE_SIZE=lots\n",
    "MAX_SOURCE_SIZE=1.5\n",
    "MAX_SOURCE_SIZE=-1\n",
    "MAX_SOURCE_SIZE=10KB\n",
    "REQUIRE_TLS=\n",
])
def test_invalid_config_file_value_fails_startup(config, text):
    assert_startup_failure({"DATAGATE_CONFIG": config(text)}, "cfg_bad")


@pytest.mark.parametrize("env", [
    {"REQUIRE_TLS": "maybe"},
    {"MAX_SOURCE_SIZE": "abc"},
    {"MAX_SOURCE_SIZE": "-5"},
    {"CACHE_ENABLED": "nope"},
])
def test_invalid_environment_value_fails_startup(env):
    env = dict(env)
    env["DATAGATE_CONFIG"] = None
    assert_startup_failure(env, "cfg_bad")


# Spec: "or read failure at startup" — a `DATAGATE_CONFIG` that cannot be read.
def test_missing_config_file_fails_startup(tmp_path):
    missing = str(tmp_path / "not-there.conf")
    assert_startup_failure({"DATAGATE_CONFIG": missing}, "cfg_bad")


def test_directory_as_config_file_fails_startup(tmp_path):
    assert_startup_failure({"DATAGATE_CONFIG": str(tmp_path)}, "cfg_bad")


def test_unreadable_config_file_fails_startup(tmp_path):
    path = write_config(tmp_path / "locked.conf", "REQUIRE_TLS=true\n")
    os.chmod(path, 0o000)
    if os.access(path, os.R_OK):  # running as root: the mode does not bite
        pytest.skip("cannot make a file unreadable here")
    try:
        assert_startup_failure({"DATAGATE_CONFIG": path}, "cfg_bad")
    finally:
        os.chmod(path, 0o600)


# Spec: valid configuration does *not* fail startup (the control case).
def test_valid_config_starts(config):
    path = config("REQUIRE_TLS=false\nCACHE_ENABLED=1\nMAX_SOURCE_SIZE=1024\n")
    assert startup_result({"DATAGATE_CONFIG": path}, "cfg_ok") is None


# ==========================================================================
# Spec: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`
#        (case-insensitive, trimmed)."
# ==========================================================================
@pytest.mark.parametrize("value", ["1", "true", "yes", "on",
                                   "TRUE", "Yes", "ON", "tRuE",
                                   " true ", "on\t"])
def test_boolean_true_spellings(value):
    with running({"REQUIRE_TLS": value, "DATAGATE_CONFIG": None},
                 "cfg_bool") as client:
        assert upload_endpoint(client).startswith("https://")


@pytest.mark.parametrize("value", ["0", "false", "no", "off",
                                   "FALSE", "No", "OFF", "oFf",
                                   " false ", "\toff\n"])
def test_boolean_false_spellings(value):
    with running({"REQUIRE_TLS": value, "DATAGATE_CONFIG": None},
                 "cfg_bool") as client:
        assert upload_endpoint(client).startswith("/datasets/")


# Spec: "strict" — nothing outside the vocabulary is accepted, and a value that
# trims to nothing is not in it either (AMBIGUITIES T62).
@pytest.mark.parametrize("value", ["", " ", "2", "-1", "y", "n", "t", "f",
                                   "truthy", "enable", "yes please", "null",
                                   "tru", "onn", "true,false"])
def test_invalid_boolean_fails_startup(value):
    assert_startup_failure({"REQUIRE_TLS": value, "DATAGATE_CONFIG": None},
                           "cfg_bad")


# The same vocabulary governs every boolean setting, in the file as well as the
# environment.
@pytest.mark.parametrize("key", ["REQUIRE_TLS", "CACHE_ENABLED"])
def test_boolean_vocabulary_is_shared(config, key):
    assert_startup_failure({"DATAGATE_CONFIG": config("%s=maybe\n" % key)},
                           "cfg_bad")
