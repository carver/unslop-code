"""Spec section: Caching and Cache Controls -- the `CACHE_ENABLED` variable."""

import pytest

from datagate_core.config import ConfigurationError
from datagate_core.server import create_app

CSV = "name,age\nada,36\n"
LATER = "name,age\ngrace,45\n"

TRUE_SPELLINGS = ["1", "true", "yes", "on", "TRUE", "Yes", "ON", "True", "oN"]
FALSE_SPELLINGS = ["0", "false", "no", "off", "FALSE", "No", "OFF", "False", "oFf"]


def convert(client, source):
    return client.get("/convert", query_string={"source": source})


# Phrase: "`/convert` caches results by default."
# Context: no CACHE_ENABLED in the environment at all.
def test_caching_is_on_when_the_variable_is_absent(configured_client, origin):
    client = configured_client(None)
    source = origin.serve("/data.csv", CSV)

    convert(client, source)
    convert(client, source)

    assert origin.downloads("/data.csv") == 1


# Phrase: "CACHE_ENABLED accepts strict case-insensitive values: - true: `1`, `true`, `yes`, `on`"
@pytest.mark.parametrize("value", TRUE_SPELLINGS)
def test_true_spellings_enable_caching(configured_client, origin, value):
    client = configured_client(value)
    source = origin.serve("/data.csv", CSV)

    convert(client, source)
    convert(client, source)

    assert origin.downloads("/data.csv") == 1


# Phrase: "- false: `0`, `false`, `no`, `off`"
@pytest.mark.parametrize("value", FALSE_SPELLINGS)
def test_false_spellings_disable_caching(configured_client, origin, value):
    client = configured_client(value)
    source = origin.serve("/data.csv", CSV)

    convert(client, source)
    convert(client, source)

    assert origin.downloads("/data.csv") == 2


# Phrase: "Invalid values fail startup."
@pytest.mark.parametrize("value", ["maybe", "2", "-1", "tru", "enabled", "y", "n", "none"])
def test_invalid_value_fails_startup(monkeypatch, value):
    monkeypatch.setenv("CACHE_ENABLED", value)

    with pytest.raises(ConfigurationError):
        create_app()


# Phrase: "Invalid values fail startup."
# Context: an empty assignment is not one of the accepted spellings (AMBIGUITIES T49).
def test_empty_value_fails_startup(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "")

    with pytest.raises(ConfigurationError):
        create_app()


# Phrase: "Boolean values are strict: `1/true/yes/on` or `0/false/no/off`
# (case-insensitive, trimmed)."
# Context: the configuration section settles the padding question (AMBIGUITIES T50).
@pytest.mark.parametrize("value", [" true", "true ", "\ttrue", "on\n", " 1 "])
def test_padded_true_value_is_trimmed(configured_client, origin, value):
    client = configured_client(value)
    source = origin.serve("/data.csv", CSV)

    convert(client, source)
    convert(client, source)

    assert origin.downloads("/data.csv") == 1


# Phrase: "Invalid values fail startup."
# Context: the failure names the variable so an operator can act on it.
def test_startup_failure_names_the_variable(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "maybe")

    with pytest.raises(ConfigurationError, match="CACHE_ENABLED"):
        create_app()


# Phrase: "Invalid values fail startup."
# Context: the CLI turns the failure into a non-zero exit (AMBIGUITIES T53).
def test_cli_exits_non_zero_on_an_invalid_value(monkeypatch):
    import datagate

    monkeypatch.setenv("CACHE_ENABLED", "maybe")

    with pytest.raises(SystemExit) as exit_info:
        datagate.main(["start"])

    assert exit_info.value.code != 0


# Phrase: "When disabled, every `/convert` request re-downloads/parses and replaces stored data."
def test_disabled_caching_re_downloads_every_request(configured_client, origin):
    client = configured_client("off")
    source = origin.serve("/data.csv", CSV)

    for _ in range(3):
        convert(client, source)

    assert origin.downloads("/data.csv") == 3


# Phrase: "When disabled, every `/convert` request re-downloads/parses and replaces stored data."
# Context: the stored rows follow the newest download.
def test_disabled_caching_replaces_stored_data(configured_client, origin):
    client = configured_client("false")
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(client, source).get_json()["endpoint"]

    origin.serve("/data.csv", LATER)
    convert(client, source)

    assert client.get(endpoint).get_json()["rows"] == [["grace", 45]]


# Phrase: "When disabled, every `/convert` request re-downloads/parses and replaces stored data."
# Context: replacement means the same dataset id, not a second dataset.
def test_disabled_caching_keeps_the_dataset_id_stable(configured_client, origin):
    client = configured_client("0")
    source = origin.serve("/data.csv", CSV)

    first = convert(client, source).get_json()
    origin.serve("/data.csv", LATER)
    second = convert(client, source).get_json()

    assert first == second
