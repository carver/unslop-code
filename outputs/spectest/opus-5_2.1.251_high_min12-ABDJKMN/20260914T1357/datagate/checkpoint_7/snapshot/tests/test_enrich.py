"""Spec tests for "Optional Dataset Enrichment". Each section quotes its phrase."""
import urllib.parse

import pytest

from conftest import (Client, free_port, make_xls, make_xlsx, spawn_env, stop,
                      wait_for_port)

SIMPLE = "name,age\nada,36\ngrace,45\n"
OTHER = "name,age\nlin,29\nada,36\ngrace,45\n"
SHEET = [["name", "age", "city"], ["ada", 36, "London"], ["grace", 45, "Paris"]]

META_FIELDS = ("dataset_summary", "column_details")


def path_of(url):
    return urllib.parse.urlsplit(url).path


def hits(origin, url):
    """How many times the origin has served this URL (0 if never)."""
    return origin.hits.get(path_of(url), 0)


def payload_of(client, endpoint, query=""):
    status, _, data = client.get(endpoint + query)
    assert status == 200, data
    return data


def convert_ok(client, url, extra=""):
    """Convert `url` (optionally with extra query text) and return the body."""
    status, _, data = client.convert(url, extra=extra)
    assert status == 200, data
    return data


def query_after(client, url, extra=""):
    """Convert then query: the /datasets/<id> payload for `url`."""
    return payload_of(client, convert_ok(client, url, extra=extra)["endpoint"])


def assert_error_envelope(status, data, expected):
    """Spec: errors keep the `{"ok": false, "error": "<message>"}` envelope."""
    assert status == expected, data
    assert data is not None, "expected a JSON body"
    assert data["ok"] is False
    assert isinstance(data["error"], str) and data["error"].strip()


@pytest.fixture
def source(origin, csv_url):
    """A mutable source: returns (url, rewrite) where rewrite swaps the body."""
    def make(body, name="enrich", status=200, content_type="text/csv"):
        url = csv_url(body, name=name, status=status, content_type=content_type)

        def rewrite(new_body, status=200, content_type="text/csv"):
            origin.add(path_of(url), new_body, status=status,
                       content_type=content_type)

        return url, rewrite
    return make


# ==========================================================================
# Spec: "`/convert` supports optional ingestion enrichment with `enrich=yes`."
# ==========================================================================
def test_convert_accepts_enrich_yes(server, csv_url):
    status, _, data = server.convert(csv_url(SIMPLE), extra="enrich=yes")
    assert status == 200, data
    assert data["ok"] is True


# Spec: "optional" — a conversion without `enrich` still succeeds unchanged.
def test_enrich_is_optional(server, csv_url):
    status, _, data = server.convert(csv_url(SIMPLE))
    assert status == 200, data
    assert data["ok"] is True


# Spec: "optional ingestion enrichment" — enrichment does not disturb the rest
# of /convert: `charset` and `force` still work alongside it.
def test_enrich_composes_with_other_convert_parameters(server, csv_url):
    url = csv_url("name,age\nköln,1\n".encode("utf-8"), name="enrich-charset")
    status, _, data = server.convert(url, charset="utf-8", extra="enrich=yes")
    assert status == 200, data
    payload = payload_of(server, data["endpoint"])
    assert payload["rows"] == [["köln", 1]]
    assert "dataset_summary" in payload


# ==========================================================================
# Spec: "Only exact `enrich=yes` enables enrichment."
# ==========================================================================
def test_exact_enrich_yes_enables_enrichment(server, csv_url):
    payload = query_after(server, csv_url(SIMPLE), extra="enrich=yes")
    assert "dataset_summary" in payload
    assert "column_details" in payload


# Spec: "Only exact `enrich=yes`" — enrichment survives to later plain queries
# of the same dataset (it is a property of the stored dataset).
def test_enrichment_is_visible_on_every_query(server, csv_url):
    endpoint = convert_ok(server, csv_url(SIMPLE), extra="enrich=yes")["endpoint"]
    for _ in range(3):
        assert "dataset_summary" in payload_of(server, endpoint)


# ==========================================================================
# Spec: "All other states keep enrichment off."
# ==========================================================================
@pytest.mark.parametrize("extra", [
    "",                     # absent
    "enrich",               # bare flag, no value
    "enrich=",              # empty value
    "enrich=YES",           # wrong case
    "enrich=Yes",
    "enrich=yes%20",        # trailing space
    "enrich=%20yes",        # leading space
    "enrich=yess",
    "enrich=y",
    "enrich=1",
    "enrich=true",
    "enrich=on",
    "enrich=no",
    "enrich=false",
    "enrich=0",
])
def test_other_states_keep_enrichment_off(server, csv_url, extra):
    payload = query_after(server, csv_url(SIMPLE), extra=extra)
    for field in META_FIELDS:
        assert field not in payload, extra


# Spec: "All other states keep enrichment off." — off is not an error: the
# request still succeeds with the normal envelope.
@pytest.mark.parametrize("extra", ["enrich", "enrich=", "enrich=maybe",
                                   "enrich=YES", "enrich=1"])
def test_other_states_are_not_errors(server, csv_url, extra):
    status, _, data = server.convert(csv_url(SIMPLE), extra=extra)
    assert status == 200, data
    assert data["ok"] is True


# ==========================================================================
# Spec: 'Success response remains {"ok": true, "endpoint": "/datasets/<id>"}'
# ==========================================================================
def test_enriched_success_response_shape(server, csv_url):
    status, _, data = server.convert(csv_url(SIMPLE), extra="enrich=yes")
    assert status == 200
    assert data == {"ok": True, "endpoint": data["endpoint"]}
    assert set(data) == {"ok", "endpoint"}
    assert data["endpoint"].startswith("/datasets/")


# Spec: the success response "remains" the same — byte-for-byte the same body
# an unenriched conversion of the same URL returns.
def test_enriched_response_matches_unenriched_response(server, csv_url):
    url = csv_url(SIMPLE, name="same-envelope")
    plain = convert_ok(server, url)
    enriched = convert_ok(server, url, extra="enrich=yes")
    assert enriched == plain


# Spec: the dataset id does not depend on `enrich`.
def test_enrich_does_not_change_the_dataset_id(server, csv_url):
    url = csv_url(SIMPLE, name="stable-id")
    a = convert_ok(server, url, extra="enrich=yes")["endpoint"]
    b = convert_ok(server, url)["endpoint"]
    assert a == b


# ==========================================================================
# Spec: "For enriched CSV datasets, add: `dataset_summary` with at least
#        `filetype`, `row_count`, `column_count`"
# ==========================================================================
def test_csv_dataset_summary_fields(server, csv_url):
    payload = query_after(server, csv_url(SIMPLE), extra="enrich=yes")
    summary = payload["dataset_summary"]
    assert isinstance(summary, dict)
    assert set(summary) >= {"filetype", "row_count", "column_count"}
    assert summary["row_count"] == 2
    assert summary["column_count"] == 2


# Spec: "`row_count`" counts data rows, not the header row.
def test_row_count_excludes_the_header(server, csv_url):
    body = "a,b\n" + "".join("%d,%d\n" % (i, i) for i in range(1, 8))
    payload = query_after(server, csv_url(body), extra="enrich=yes")
    assert payload["dataset_summary"]["row_count"] == 7
    assert len(payload["rows"]) == 7


# Spec: "`column_count`" matches the reported columns.
def test_column_count_matches_columns(server, csv_url):
    payload = query_after(server, csv_url("a,b,c,d\n1,2,3,4\n"),
                          extra="enrich=yes")
    assert payload["columns"] == ["a", "b", "c", "d"]
    assert payload["dataset_summary"]["column_count"] == 4


# Spec: "`filetype`" — a delimited text source reports the CSV label (T102).
def test_csv_filetype_label(server, csv_url):
    payload = query_after(server, csv_url(SIMPLE), extra="enrich=yes")
    assert payload["dataset_summary"]["filetype"] == "csv"


# ==========================================================================
# Spec: "`column_details` keyed by column name with at least `type`,
#        `distinct_count`, `missing_count`"
# ==========================================================================
def test_column_details_keyed_by_column_name(server, csv_url):
    payload = query_after(server, csv_url("name,age,city\nada,36,London\n"),
                          extra="enrich=yes")
    details = payload["column_details"]
    assert isinstance(details, dict)
    assert set(details) == {"name", "age", "city"}


def test_column_details_fields(server, csv_url):
    payload = query_after(server, csv_url(SIMPLE), extra="enrich=yes")
    for name, entry in payload["column_details"].items():
        assert set(entry) >= {"type", "distinct_count", "missing_count"}, name
        assert isinstance(entry["distinct_count"], int)
        assert isinstance(entry["missing_count"], int)


# Spec: "`distinct_count`" — repeated values count once.
def test_distinct_count_counts_unique_values(server, csv_url):
    body = "tag,n\nx,1\ny,2\nx,3\nx,4\nz,5\n"
    payload = query_after(server, csv_url(body), extra="enrich=yes")
    assert payload["column_details"]["tag"]["distinct_count"] == 3


# Spec: "`missing_count`" — empty cells are the missing ones (T104).
def test_missing_count_counts_empty_cells(server, csv_url):
    body = "a,b\nx,1\n,2\n,3\ny,4\n"
    payload = query_after(server, csv_url(body), extra="enrich=yes")
    assert payload["column_details"]["a"]["missing_count"] == 2
    assert payload["column_details"]["b"]["missing_count"] == 0


# ==========================================================================
# Spec: "Type labels: `text`, `number`, `integer`, `float`."
# ==========================================================================
def test_type_labels_come_from_the_published_set(server, csv_url):
    body = ("word,whole,frac,mixed,empty\n"
            "ada,1,1.5,1,\n"
            "lin,2,2.5,2.5,\n")
    payload = query_after(server, csv_url(body), extra="enrich=yes")
    labels = {name: entry["type"]
              for name, entry in payload["column_details"].items()}
    assert set(labels.values()) <= {"text", "number", "integer", "float"}
    assert labels["word"] == "text"
    assert labels["whole"] == "integer"
    assert labels["frac"] == "float"


# Spec: "Type labels: ... `integer`" — an all-whole-number column.
def test_integer_label(server, csv_url):
    payload = query_after(server, csv_url("n,s\n1,a\n2,b\n-3,c\n"), extra="enrich=yes")
    assert payload["column_details"]["n"]["type"] == "integer"


# Spec: "Type labels: ... `float`" — a fractional column.
def test_float_label(server, csv_url):
    payload = query_after(server, csv_url("x,s\n1.5,a\n2.25,b\n"), extra="enrich=yes")
    assert payload["column_details"]["x"]["type"] == "float"


# Spec: "Type labels: `text` ..." — a column with non-numeric values.
def test_text_label(server, csv_url):
    payload = query_after(server, csv_url("s,n\nada,1\n12,2\n"), extra="enrich=yes")
    assert payload["column_details"]["s"]["type"] == "text"


# ==========================================================================
# Spec: "For enriched spreadsheet datasets, add only `dataset_summary` with
#        `filetype: "excel"`."
# ==========================================================================
@pytest.mark.parametrize("builder", [make_xlsx, make_xls])
def test_spreadsheet_summary_filetype_excel(server, csv_url, builder):
    url = csv_url(builder([("S", SHEET)]), name="xl-enrich",
                  content_type="application/octet-stream")
    payload = query_after(server, url, extra="enrich=yes")
    assert payload["dataset_summary"]["filetype"] == "excel"


# Spec: "add only `dataset_summary`" — no `column_details` for spreadsheets.
@pytest.mark.parametrize("builder", [make_xlsx, make_xls])
def test_spreadsheet_has_no_column_details(server, csv_url, builder):
    url = csv_url(builder([("S", SHEET)]), name="xl-nodetails",
                  content_type="application/octet-stream")
    payload = query_after(server, url, extra="enrich=yes")
    assert "column_details" not in payload


# Spec: a non-enriched spreadsheet gets neither field.
def test_unenriched_spreadsheet_has_no_metadata(server, csv_url):
    url = csv_url(make_xlsx([("S", SHEET)]), name="xl-plain",
                  content_type="application/octet-stream")
    payload = query_after(server, url)
    for field in META_FIELDS:
        assert field not in payload


# ==========================================================================
# Spec: "Non-enriched responses omit both metadata fields (no `null`/empty
#        objects)."
# ==========================================================================
def test_non_enriched_response_omits_both_fields(server, csv_url):
    payload = query_after(server, csv_url(SIMPLE))
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# Spec: "no `null`/empty objects" — the keys are truly absent, which is
# stronger than being present-and-falsey.
def test_non_enriched_keys_are_absent_not_null(server, csv_url):
    payload = query_after(server, csv_url(SIMPLE))
    assert payload.get("dataset_summary", "absent") == "absent"
    assert payload.get("column_details", "absent") == "absent"
    assert set(payload) == {"ok", "columns", "rows", "total", "query_ms"}


# ==========================================================================
# Spec: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
# ==========================================================================
def test_enrichment_does_not_change_the_other_fields(server, csv_url):
    body = "name,age\nada,36\ngrace,45\nlin,29\n"
    plain = query_after(server, csv_url(body, name="unchanged-plain"))
    rich = query_after(server, csv_url(body, name="unchanged-rich"),
                       extra="enrich=yes")
    assert rich["ok"] == plain["ok"] is True
    assert rich["columns"] == plain["columns"]
    assert rich["rows"] == plain["rows"]
    assert rich["total"] == plain["total"] == 3
    assert isinstance(rich["query_ms"], (int, float))


# Spec: "`rows` ... and `total` do not change" — control parameters and filters
# still shape the response exactly as before on an enriched dataset.
def test_controls_and_filters_unchanged_when_enriched(server, csv_url):
    body = "n,tag\n" + "".join("%d,%s\n" % (i, "even" if i % 2 == 0 else "odd")
                               for i in range(1, 11))
    endpoint = convert_ok(server, csv_url(body, name="enrich-controls"),
                          extra="enrich=yes")["endpoint"]
    payload = payload_of(server, endpoint, "?tag__exact=even&_size=2")
    assert payload["total"] == 5
    assert payload["rows"] == [[2, "even"], [4, "even"]]


# Spec: "`rows`, `columns` ... do not change" — the object shape is unaffected.
def test_objects_shape_unchanged_when_enriched(server, csv_url):
    endpoint = convert_ok(server, csv_url(SIMPLE, name="enrich-objects"),
                          extra="enrich=yes")["endpoint"]
    payload = payload_of(server, endpoint, "?_shape=objects")
    assert payload["rows"][0] == {"rowid": 1, "name": "ada", "age": 36}
    assert "dataset_summary" in payload


# ==========================================================================
# Spec: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion and
#        upgrades stored state."
# ==========================================================================
def test_enrich_yes_re_ingests_a_cached_plain_dataset(server, origin, source):
    url, _ = source(SIMPLE, name="upgrade-refetch")
    convert_ok(server, url)
    before = hits(origin, url)
    convert_ok(server, url, extra="enrich=yes")
    assert hits(origin, url) == before + 1


def test_enrich_yes_upgrades_stored_state(server, source):
    url, _ = source(SIMPLE, name="upgrade-state")
    endpoint = convert_ok(server, url)["endpoint"]
    assert "dataset_summary" not in payload_of(server, endpoint)
    convert_ok(server, url, extra="enrich=yes")
    upgraded = payload_of(server, endpoint)
    assert upgraded["dataset_summary"]["row_count"] == 2
    assert "column_details" in upgraded


# Spec: "upgrades stored state" — the upgrade persists for later plain
# conversions of the same URL, which are then ordinary cache hits.
def test_upgrade_survives_a_later_plain_convert(server, origin, source):
    url, _ = source(SIMPLE, name="upgrade-persists")
    endpoint = convert_ok(server, url)["endpoint"]
    convert_ok(server, url, extra="enrich=yes")
    before = hits(origin, url)
    convert_ok(server, url)
    assert hits(origin, url) == before          # cache hit, no re-download
    assert "dataset_summary" in payload_of(server, endpoint)


# ==========================================================================
# Spec: "`enrich=yes` on a cached enriched dataset may use cache."
# ==========================================================================
def test_repeat_enrich_yes_may_use_cache(server, origin, source):
    url, _ = source(SIMPLE, name="enriched-cache")
    first = convert_ok(server, url, extra="enrich=yes")
    before = hits(origin, url)
    second = convert_ok(server, url, extra="enrich=yes")
    assert second == first
    # "may use cache": this implementation does, so no second download.
    assert hits(origin, url) == before
    assert "dataset_summary" in payload_of(server, first["endpoint"])


# Spec: "may use cache" — a cached enriched dataset serves the metadata it was
# ingested with, even after the source changes underneath it.
def test_cached_enriched_metadata_is_not_recomputed(server, source):
    url, rewrite = source(SIMPLE, name="enriched-stale")
    endpoint = convert_ok(server, url, extra="enrich=yes")["endpoint"]
    rewrite(OTHER)
    convert_ok(server, url, extra="enrich=yes")
    assert payload_of(server, endpoint)["dataset_summary"]["row_count"] == 2


# ==========================================================================
# Spec: "Requests without re-ingestion do not change stored enrichment state."
# ==========================================================================
def test_plain_cache_hit_keeps_enriched_state(server, source):
    url, _ = source(SIMPLE, name="keep-enriched")
    endpoint = convert_ok(server, url, extra="enrich=yes")["endpoint"]
    convert_ok(server, url)                      # cache hit, no re-ingestion
    assert "dataset_summary" in payload_of(server, endpoint)


@pytest.mark.parametrize("extra", ["", "enrich=no", "enrich=YES"])
def test_cache_hit_keeps_plain_state(server, source, extra):
    url, _ = source(SIMPLE, name="keep-plain")
    endpoint = convert_ok(server, url)["endpoint"]
    convert_ok(server, url, extra=extra)         # cache hit, no re-ingestion
    for field in META_FIELDS:
        assert field not in payload_of(server, endpoint)


# Spec: "Requests without re-ingestion" — querying a dataset never changes its
# stored enrichment state either.
def test_queries_do_not_change_stored_state(server, source):
    url, _ = source(SIMPLE, name="query-no-change")
    endpoint = convert_ok(server, url, extra="enrich=yes")["endpoint"]
    payload_of(server, endpoint, "?_size=1")
    payload_of(server, endpoint, "?name__exact=ada")
    assert "dataset_summary" in payload_of(server, endpoint)


# ==========================================================================
# Spec: "Re-ingestion recomputes metadata from current source bytes."
# ==========================================================================
def test_forced_re_ingestion_recomputes_metadata(server, source):
    url, rewrite = source(SIMPLE, name="recompute")
    endpoint = convert_ok(server, url, extra="enrich=yes")["endpoint"]
    assert payload_of(server, endpoint)["dataset_summary"]["row_count"] == 2
    rewrite(OTHER)
    convert_ok(server, url, extra="enrich=yes&force")
    payload = payload_of(server, endpoint)
    assert payload["dataset_summary"]["row_count"] == 3
    assert payload["rows"][0] == ["lin", 29]


# Spec: "recomputes metadata from current source bytes" — new columns produce
# new `column_details` keys, and old ones disappear.
def test_re_ingestion_recomputes_column_details(server, source):
    url, rewrite = source(SIMPLE, name="recompute-cols")
    endpoint = convert_ok(server, url, extra="enrich=yes")["endpoint"]
    assert set(payload_of(server, endpoint)["column_details"]) == {"name", "age"}
    rewrite("city,zip\nKöln,50667\n")
    convert_ok(server, url, extra="force&enrich=yes")
    payload = payload_of(server, endpoint)
    assert set(payload["column_details"]) == {"city", "zip"}
    assert payload["dataset_summary"]["column_count"] == 2


# Spec: "Re-ingestion recomputes metadata" — the upgrade of a cached plain
# dataset reads the current bytes, not the bytes cached earlier.
def test_upgrade_reads_current_bytes(server, source):
    url, rewrite = source(SIMPLE, name="upgrade-current-bytes")
    endpoint = convert_ok(server, url)["endpoint"]
    rewrite(OTHER)
    convert_ok(server, url, extra="enrich=yes")
    payload = payload_of(server, endpoint)
    assert payload["dataset_summary"]["row_count"] == 3
    assert payload["total"] == 3


# ==========================================================================
# Spec: "`enrich` applies only on `/convert`."
# ==========================================================================
def test_enrich_on_the_query_endpoint_does_nothing(server, csv_url):
    endpoint = convert_ok(server, csv_url(SIMPLE, name="query-enrich"))["endpoint"]
    status, _, payload = server.get(endpoint + "?enrich=yes")
    assert status == 200, payload
    for field in META_FIELDS:
        assert field not in payload


def test_enrich_on_export_is_inert(server, csv_url):
    endpoint = convert_ok(server, csv_url(SIMPLE, name="export-enrich"))["endpoint"]
    status, headers, body = server.raw(endpoint + "/export?enrich=yes")
    assert status == 200, body
    assert headers["Content-Type"].startswith("text/csv")
    assert body.decode("utf-8").splitlines()[0] == "name,age"


def test_enrich_on_upload_does_not_enrich(up):
    status, _, data = up.upload(SIMPLE.encode("utf-8"), path="/upload?enrich=yes")
    assert status == 200, data
    payload = payload_of(up, data["endpoint"])
    for field in META_FIELDS:
        assert field not in payload


# ==========================================================================
# Spec: "Enrichment failures return standard JSON errors and must not
#        downgrade to non-enriched storage."
# ==========================================================================
def test_failed_enriched_re_ingestion_returns_standard_error(server, source):
    url, rewrite = source(SIMPLE, name="fail-error")
    convert_ok(server, url, extra="enrich=yes")
    rewrite("not a table at all", status=500)
    status, _, data = server.convert(url, extra="enrich=yes&force")
    assert_error_envelope(status, data, 404)


def test_failed_enriched_re_ingestion_keeps_enriched_storage(server, source):
    url, rewrite = source(SIMPLE, name="fail-keeps-enriched")
    endpoint = convert_ok(server, url, extra="enrich=yes")["endpoint"]
    rewrite("not a table at all")
    assert server.convert(url, extra="enrich=yes&force")[0] == 400
    payload = payload_of(server, endpoint)
    assert payload["dataset_summary"]["row_count"] == 2
    assert payload["rows"] == [["ada", 36], ["grace", 45]]


# Spec: "must not downgrade to non-enriched storage" — a failed upgrade of a
# plain cached dataset stores nothing at all; the plain dataset survives.
def test_failed_upgrade_leaves_the_plain_dataset_intact(server, source):
    url, rewrite = source(SIMPLE, name="fail-upgrade")
    endpoint = convert_ok(server, url)["endpoint"]
    rewrite("", status=200)
    assert server.convert(url, extra="enrich=yes")[0] == 400
    payload = payload_of(server, endpoint)
    assert payload["rows"] == [["ada", 36], ["grace", 45]]
    assert "dataset_summary" not in payload


# Spec: "Enrichment failures return standard JSON errors" — a first-time
# enriched conversion that fails is the ordinary error for that failure.
def test_first_enriched_conversion_failure(server, source):
    url, rewrite = source("name,age\nada,36\n", name="fail-first", status=404)
    status, _, data = server.convert(url, extra="enrich=yes")
    assert_error_envelope(status, data, 404)
    # Nothing was stored, so the next (plain) conversion is a fresh ingestion.
    rewrite(SIMPLE)
    payload = query_after(server, url)
    assert payload["rows"] == [["ada", 36], ["grace", 45]]
    assert "dataset_summary" not in payload


# ==========================================================================
# Spec: enrichment under `CACHE_ENABLED=false` — every /convert re-ingests, so
# the stored state always follows the request that just ran.
# ==========================================================================
def test_enrichment_without_caching(origin, csv_url):
    port = free_port()
    proc = spawn_env(port, {"CACHE_ENABLED": "false"}, tag="enrich_off")
    try:
        assert wait_for_port("127.0.0.1", port), "datagate did not start"
        client = Client("http://127.0.0.1:%d" % port)
        url = csv_url(SIMPLE, name="nocache-enrich")
        endpoint = convert_ok(client, url, extra="enrich=yes")["endpoint"]
        assert "dataset_summary" in payload_of(client, endpoint)
        convert_ok(client, url)
        assert "dataset_summary" not in payload_of(client, endpoint)
    finally:
        stop(proc)


# ==========================================================================
# Interpretations recorded in AMBIGUITIES.md (T101-T113)
# ==========================================================================

# T101 — a repeated `enrich` is not an error; the first value decides.
def test_t101_repeated_enrich_is_not_an_error(server, csv_url):
    status, _, data = server.convert(csv_url(SIMPLE, name="t101"),
                                     extra="enrich=yes&enrich=no")
    assert status == 200, data
    assert data["ok"] is True


def test_t101_first_value_decides(server, csv_url):
    on = query_after(server, csv_url(SIMPLE, name="t101-on"),
                     extra="enrich=yes&enrich=no")
    assert "dataset_summary" in on
    off = query_after(server, csv_url(SIMPLE, name="t101-off"),
                      extra="enrich=no&enrich=yes")
    assert "dataset_summary" not in off


# T102 — every delimited text source reports `filetype: "csv"`, whatever the
# sniffed delimiter was.
@pytest.mark.parametrize("body", ["name;age\nada;36\n", "name\tage\nada\t36\n",
                                  "name,age\nada,36\n"])
def test_t102_delimiters_all_report_csv(server, csv_url, body):
    payload = query_after(server, csv_url(body, name="t102"), extra="enrich=yes")
    assert payload["dataset_summary"]["filetype"] == "csv"


# T103 — integer/float/number/text mapping; `number` is the mixed numeric case.
def test_t103_mixed_numeric_column_is_number(server, csv_url):
    payload = query_after(server, csv_url("m,s\n1,a\n2.5,b\n3,c\n", name="t103"),
                          extra="enrich=yes")
    assert payload["column_details"]["m"]["type"] == "number"


def test_t103_numbers_with_any_text_are_text(server, csv_url):
    payload = query_after(server, csv_url("m,s\n1,a\n2,b\nn/a,c\n", name="t103-text"),
                          extra="enrich=yes")
    assert payload["column_details"]["m"]["type"] == "text"


def test_t103_missing_values_do_not_change_the_label(server, csv_url):
    payload = query_after(server, csv_url("i,f\n1,\n,2.5\n", name="t103-blank"),
                          extra="enrich=yes")
    labels = payload["column_details"]
    assert labels["i"]["type"] == "integer"
    assert labels["f"]["type"] == "float"


# T104 — missing means the empty value: a short row's padding counts too.
def test_t104_short_row_padding_counts_as_missing(server, csv_url):
    payload = query_after(server, csv_url("a,b,c\n1,2\n1,2,3\n", name="t104"),
                          extra="enrich=yes")
    assert payload["column_details"]["c"]["missing_count"] == 1


# T105 — `distinct_count` counts present values only.
def test_t105_distinct_count_excludes_missing(server, csv_url):
    payload = query_after(server, csv_url("a,n\nx,1\n,2\nx,3\ny,4\n", name="t105"),
                          extra="enrich=yes")
    entry = payload["column_details"]["a"]
    assert entry["missing_count"] == 1
    assert entry["distinct_count"] == 2


def test_t105_all_missing_column(server, csv_url):
    payload = query_after(server, csv_url("a,b\n1,\n2,\n", name="t105-empty"),
                          extra="enrich=yes")
    entry = payload["column_details"]["b"]
    assert entry["missing_count"] == 2
    assert entry["distinct_count"] == 0


# T106 — the metadata is dataset-wide and frozen at ingestion: paging,
# filtering and sorting never change it, while `total` still tracks filters.
def test_t106_metadata_ignores_query_controls(server, csv_url):
    body = "n,tag\n" + "".join("%d,%s\n" % (i, "even" if i % 2 == 0 else "odd")
                               for i in range(1, 11))
    endpoint = convert_ok(server, csv_url(body, name="t106"),
                          extra="enrich=yes")["endpoint"]
    full = payload_of(server, endpoint)["dataset_summary"]
    assert full["row_count"] == 10
    paged = payload_of(server, endpoint, "?_size=2&_offset=4")
    assert paged["dataset_summary"] == full
    assert len(paged["rows"]) == 2
    filtered = payload_of(server, endpoint, "?tag__exact=even")
    assert filtered["dataset_summary"]["row_count"] == 10
    assert filtered["total"] == 5
    assert filtered["column_details"]["tag"]["distinct_count"] == 2


# T107 — a spreadsheet summary carries the counts as well as the filetype.
def test_t107_spreadsheet_summary_has_counts(server, csv_url):
    url = csv_url(make_xlsx([("S", SHEET)]), name="t107",
                  content_type="application/octet-stream")
    summary = query_after(server, url, extra="enrich=yes")["dataset_summary"]
    assert summary["filetype"] == "excel"
    assert summary["row_count"] == 2
    assert summary["column_count"] == 3


# T108 — a successful re-ingestion without `enrich=yes` downgrades the stored
# state; only requests that do not re-ingest leave it alone.
def test_t108_forced_plain_re_ingestion_downgrades(server, source):
    url, _ = source(SIMPLE, name="t108")
    endpoint = convert_ok(server, url, extra="enrich=yes")["endpoint"]
    assert "dataset_summary" in payload_of(server, endpoint)
    convert_ok(server, url, extra="force")
    payload = payload_of(server, endpoint)
    for field in META_FIELDS:
        assert field not in payload
    assert payload["rows"] == [["ada", 36], ["grace", 45]]


# T109 — enrichment state is part of the stored dataset and survives a restart.
def test_t109_enrichment_survives_restart(tmp_path, csv_url, origin):
    from conftest import running
    store = str(tmp_path / "enrich-store")
    env = {"STORAGE_DIR": store, "DATAGATE_CONFIG": None}
    url = csv_url(SIMPLE, name="t109")
    with running(env, "enrich_restart") as client:
        endpoint = convert_ok(client, url, extra="enrich=yes")["endpoint"]
        assert "dataset_summary" in payload_of(client, endpoint)
    before = hits(origin, url)
    with running(env, "enrich_restart") as client:
        payload = payload_of(client, endpoint)
        assert payload["rows"] == [["ada", 36], ["grace", 45]]
        assert payload["dataset_summary"]["row_count"] == 2
        assert "column_details" in payload
    assert hits(origin, url) == before          # served from the store


# T110 — `enrich` is inert outside /convert; an enriched dataset's export is
# still plain CSV with no metadata smuggled in.
def test_t110_export_of_an_enriched_dataset_is_plain_csv(server, csv_url):
    endpoint = convert_ok(server, csv_url(SIMPLE, name="t110"),
                          extra="enrich=yes")["endpoint"]
    status, headers, body = server.raw(endpoint + "/export")
    assert status == 200
    assert headers["Content-Type"].startswith("text/csv")
    text = body.decode("utf-8")
    assert "dataset_summary" not in text
    assert text.splitlines()[0] == "name,age"


# T111 — duplicate column names collide in `column_details`: last one wins.
def test_t111_duplicate_column_names_last_wins(server, csv_url):
    body = "a,a\n1,x\n2,y\n"
    payload = query_after(server, csv_url(body, name="t111"), extra="enrich=yes")
    assert payload["columns"] == ["a", "a"]
    details = payload["column_details"]
    assert set(details) == {"a"}
    assert details["a"]["type"] == "text"
    assert payload["dataset_summary"]["column_count"] == 2


# T112 — an enrichment failure is the ordinary error for that failure, and the
# previously stored dataset is left exactly as it was.
@pytest.mark.parametrize("body,status,expected", [
    ("not a table at all", 200, 400),        # unparseable source
    ("", 200, 400),                          # empty source
    (SIMPLE, 503, 404),                      # upstream failure
])
def test_t112_failure_statuses_and_no_downgrade(server, source, body, status,
                                                expected):
    url, rewrite = source(SIMPLE, name="t112")
    endpoint = convert_ok(server, url, extra="enrich=yes")["endpoint"]
    rewrite(body, status=status)
    got, _, data = server.convert(url, extra="enrich=yes&force")
    assert_error_envelope(got, data, expected)
    payload = payload_of(server, endpoint)
    assert payload["rows"] == [["ada", 36], ["grace", 45]]
    assert payload["dataset_summary"]["row_count"] == 2


# T113 — a column with no present values is labelled `text`.
def test_t113_all_missing_column_is_text(server, csv_url):
    payload = query_after(server, csv_url("a,b\n1,\n2,\n", name="t113"),
                          extra="enrich=yes")
    assert payload["column_details"]["b"]["type"] == "text"
