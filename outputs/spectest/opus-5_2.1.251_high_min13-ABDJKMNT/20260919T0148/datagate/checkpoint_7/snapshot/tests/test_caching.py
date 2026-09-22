"""Spec section: Caching and Cache Controls -- cache behaviour and `force`."""

import pytest

CSV = "name,age\nada,36\n"
LATER = "name,age\ngrace,45\n"


def convert(client, source, **params):
    return client.get("/convert", query_string={"source": source, **params})


@pytest.fixture()
def cached(client, origin):
    """Convert `/data.csv` once and hand back its source URL and endpoint."""
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(client, source).get_json()["endpoint"]
    return source, endpoint


# Phrase: "With caching enabled, repeated `/convert` requests for the same source URL
# can return the cached dataset id without re-downloading."
def test_repeated_convert_does_not_re_download(client, cached, origin):
    source, _ = cached

    convert(client, source)

    assert origin.downloads("/data.csv") == 1


# Phrase: "... can return the cached dataset id ..."
def test_repeated_convert_returns_the_cached_id(client, cached):
    source, endpoint = cached

    assert convert(client, source).get_json()["endpoint"] == endpoint


# Phrase: "... without re-downloading."
# Context: the cached rows are served even after the origin changed.
def test_cache_hit_serves_the_originally_parsed_rows(client, cached, origin):
    source, endpoint = cached
    origin.serve("/data.csv", LATER)

    convert(client, source)

    assert client.get(endpoint).get_json()["rows"] == [["ada", 36]]


# Phrase: "... without re-downloading."
# Context: a hit needs no reachable origin at all.
def test_cache_hit_survives_an_origin_that_now_fails(client, cached, origin):
    source, _ = cached
    origin.serve("/data.csv", "boom", status=500)

    assert convert(client, source).status_code == 200


# Phrase: "Cache responses are identical to fresh parse responses."
def test_cache_response_is_identical_to_the_fresh_one(client, origin):
    source = origin.serve("/data.csv", CSV)

    fresh = convert(client, source)
    hit = convert(client, source)

    assert (hit.status_code, hit.get_json()) == (fresh.status_code, fresh.get_json())


# Phrase: "Cache responses are identical to fresh parse responses."
# Context: no cache marker is added to the envelope (AMBIGUITIES T55).
def test_cache_response_carries_no_extra_fields(client, cached):
    source, _ = cached

    assert set(convert(client, source).get_json()) == {"ok", "endpoint"}


# Phrase: "`/convert` caches results by default."
# Context: caching is per source URL, not shared between sources.
def test_each_source_is_cached_independently(client, origin):
    one = origin.serve("/one.csv", CSV)
    two = origin.serve("/two.csv", LATER)

    convert(client, one)
    convert(client, two)

    assert (origin.downloads("/one.csv"), origin.downloads("/two.csv")) == (1, 1)


# Phrase: "With caching enabled ..."
# Context: `charset` is not part of the cache key (AMBIGUITIES T48).
def test_cache_hit_ignores_a_later_charset(client, cached):
    source, _ = cached

    assert convert(client, source, charset="klingon-9").status_code == 200


# Phrase: "`force` is a presence flag. If present once, it forces re-ingestion"
def test_force_re_downloads(client, cached, origin):
    source, _ = cached

    client.get("/convert", query_string=f"source={source}&force")

    assert origin.downloads("/data.csv") == 2


# Phrase: "... and replaces the cached dataset."
def test_force_replaces_the_cached_dataset(client, cached, origin):
    source, endpoint = cached
    origin.serve("/data.csv", LATER)

    client.get("/convert", query_string=f"source={source}&force")

    assert client.get(endpoint).get_json()["rows"] == [["grace", 45]]


# Phrase: "... replaces the cached dataset."
# Context: replacement keeps the id, so the response is the ordinary envelope.
def test_force_returns_the_same_endpoint(client, cached):
    source, endpoint = cached

    response = client.get("/convert", query_string=f"source={source}&force")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "endpoint": endpoint}


# Phrase: "`force` is a presence flag."
# Context: the value carried is irrelevant (AMBIGUITIES T51).
@pytest.mark.parametrize("spelling", ["force", "force=", "force=1", "force=0", "force=no"])
def test_force_forces_whatever_value_it_carries(client, cached, origin, spelling):
    source, _ = cached

    response = client.get("/convert", query_string=f"source={source}&{spelling}")

    assert response.status_code == 200
    assert origin.downloads("/data.csv") == 2


# Phrase: "If present once, it forces re-ingestion"
# Context: forcing a source that was never converted is an ordinary ingestion.
def test_force_on_an_unknown_source_ingests_it(client, origin):
    source = origin.serve("/fresh.csv", CSV)

    response = client.get("/convert", query_string=f"source={source}&force")

    assert response.status_code == 200
    assert client.get(response.get_json()["endpoint"]).get_json()["columns"] == ["name", "age"]


# Phrase: "Any additional `force` value is `HTTP 400`."
@pytest.mark.parametrize("query", ["force&force", "force=1&force=2", "force=&force="])
def test_repeated_force_is_400(client, cached, query):
    source, _ = cached

    response = client.get("/convert", query_string=f"source={source}&{query}")

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Any additional `force` value is `HTTP 400`."
# Context: the rejected request must not re-ingest anything.
def test_repeated_force_does_not_re_download(client, cached, origin):
    source, _ = cached

    client.get("/convert", query_string=f"source={source}&force&force")

    assert origin.downloads("/data.csv") == 1


# Phrase: "If caching is disabled, `force` has no additional effect."
def test_force_changes_nothing_when_caching_is_disabled(configured_client, origin):
    client = configured_client("off")
    source = origin.serve("/data.csv", CSV)
    plain = convert(client, source)

    forced = client.get("/convert", query_string=f"source={source}&force")

    assert forced.get_json() == plain.get_json()
    assert origin.downloads("/data.csv") == 2


# Phrase: "If caching is disabled, `force` has no additional effect."
# Context: the duplicate rule is request validation and still applies (AMBIGUITIES T52).
def test_repeated_force_is_400_even_when_caching_is_disabled(configured_client, origin):
    client = configured_client("0")
    source = origin.serve("/data.csv", CSV)

    response = client.get("/convert", query_string=f"source={source}&force&force")

    assert response.status_code == 400


# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: a remote HTTP error stays 404 on a forced re-ingestion.
def test_forced_re_ingestion_keeps_the_404_for_a_failing_origin(client, cached, origin):
    source, _ = cached
    origin.serve("/data.csv", "server exploded", status=500)

    response = client.get("/convert", query_string=f"source={source}&force")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False
    assert set(response.get_json()) == {"ok", "error"}


# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: non-tabular replacement content stays 400.
def test_forced_re_ingestion_keeps_the_400_for_non_tabular_content(client, cached, origin):
    source, _ = cached
    origin.serve("/data.csv", "<!DOCTYPE html><html><body>hi</body></html>")

    response = client.get("/convert", query_string=f"source={source}&force")

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: a bad charset on a forced re-ingestion stays 400.
def test_forced_re_ingestion_keeps_the_400_for_a_bad_charset(client, cached):
    source, _ = cached

    response = client.get(
        "/convert", query_string=f"source={source}&charset=klingon-9&force"
    )

    assert response.status_code == 400


# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: the same failure with caching disabled rather than forced.
def test_disabled_cache_re_ingestion_keeps_existing_error_codes(configured_client, origin):
    client = configured_client("no")
    source = origin.serve("/data.csv", CSV)
    convert(client, source)

    origin.serve("/data.csv", "boom", status=500)

    assert convert(client, source).status_code == 404


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
def test_failed_forced_re_ingestion_keeps_the_prior_dataset(client, cached, origin):
    source, endpoint = cached
    origin.serve("/data.csv", "boom", status=500)

    client.get("/convert", query_string=f"source={source}&force")

    dataset = client.get(endpoint)
    assert dataset.status_code == 200
    assert dataset.get_json()["rows"] == [["ada", 36]]


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: a parse failure, not only a download failure.
def test_failed_forced_parse_keeps_the_prior_dataset(client, cached, origin):
    source, endpoint = cached
    origin.serve("/data.csv", '{"name": "ada"}')

    client.get("/convert", query_string=f"source={source}&force")

    assert client.get(endpoint).get_json()["rows"] == [["ada", 36]]


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: the surviving dataset still honours filters, sorting and export.
def test_prior_dataset_stays_fully_queryable_after_a_failed_force(client, cached, origin):
    source, endpoint = cached
    origin.serve("/data.csv", "boom", status=500)
    client.get("/convert", query_string=f"source={source}&force")

    assert client.get(endpoint + "?name__exact=ada").get_json()["total"] == 1
    assert client.get(endpoint + "/export").status_code == 200


# Phrase: "When disabled, every `/convert` request re-downloads/parses and replaces stored data."
# Context: a failed re-ingestion replaces nothing (AMBIGUITIES T52 companion).
def test_failed_re_ingestion_with_caching_disabled_keeps_the_prior_dataset(
    configured_client, origin
):
    client = configured_client("off")
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(client, source).get_json()["endpoint"]

    origin.serve("/data.csv", "boom", status=500)
    convert(client, source)

    assert client.get(endpoint).get_json()["rows"] == [["ada", 36]]


# Phrase: "`force` is a presence flag."
# Context: `force` belongs to `/convert`; uploads are unaffected (AMBIGUITIES T54).
def test_upload_still_parses_every_time(client, upload):
    first = upload(CSV)
    second = upload(CSV)

    assert first.get_json() == second.get_json()
    assert client.get(first.get_json()["endpoint"]).get_json()["rows"] == [["ada", 36]]
