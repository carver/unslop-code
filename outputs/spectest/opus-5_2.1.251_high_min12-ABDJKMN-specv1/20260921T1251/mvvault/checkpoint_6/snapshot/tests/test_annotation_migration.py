"""Spec section: Annotation Auto-Migration, Rules and Category Transition."""

from __future__ import annotations

import json
import re

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

REDIRECTS = (301, 302, 303, 307, 308)


def v1_vault(make_vault, legacy, ids=("e1",), source_id="chan-1"):
    entries = [legacy.v1_entry(entry_id) for entry_id in ids]
    return make_vault(legacy.v1_catalog(entries, source_id=source_id))


def v2_vault(make_vault, legacy, ids=("e1",)):
    entries = [legacy.v2_entry(entry_id) for entry_id in ids]
    return make_vault(legacy.v2_catalog(episodes=entries))


def create(annotate, client, category, entry_id="e1", follow=False, **fields):
    payload = {"title": "Note", "timecode": "90"}
    payload.update(fields)
    return annotate.create(client, "vault", category, entry_id, payload,
                           follow=follow)


# ---------------------------------------------------------------------------
# | Vault Version | Behavior on Annotation Mutation |
# | v1 | Migrate entire catalog to v3 first, then apply annotation, then
#   persist |
# ---------------------------------------------------------------------------

# Spec: | v1 | Migrate entire catalog to v3 first ... |
def test_v1_annotation_migrates_the_catalog(serve, make_vault, legacy,
                                            annotate, workdir, helpers):
    v1_vault(make_vault, legacy)
    response = create(annotate, serve().client, "entries")
    assert response.status in REDIRECTS, response.body[:400]
    assert helpers.read_catalog(workdir)["version"] == 3


# Spec: | v1 | ... then apply annotation, then persist |
def test_v1_annotation_is_persisted(serve, make_vault, legacy, annotate,
                                    workdir):
    v1_vault(make_vault, legacy)
    create(annotate, serve().client, "entries", title="Chapter")
    stored = annotate.only(workdir, "vault", "e1", "episodes")
    assert (stored["title"], stored["timecode"]) == ("Chapter", 90)


# Spec: | v2 | Migrate entire catalog to v3 first, then apply annotation, then
#   persist |
def test_v2_annotation_migrates_the_catalog(serve, make_vault, legacy,
                                            annotate, workdir, helpers):
    v2_vault(make_vault, legacy)
    response = create(annotate, serve().client, "episodes", title="Chapter")
    assert response.status in REDIRECTS, response.body[:400]
    catalog = helpers.read_catalog(workdir)
    assert catalog["version"] == 3
    assert catalog["episodes"][0]["annotations"][0]["title"] == "Chapter"


# Spec: | v3 | Apply annotation directly |
# Context: a v3 vault is not rewritten by a migration, so its entries keep the
# `removed` history they already had.
def test_v3_annotation_does_not_migrate(serve, make_vault, catalogs, annotate,
                                        workdir, helpers):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    annotate.make(serve().client, "vault", "episodes", "e1")
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["removed"] == {catalogs.STAMP_1: False}


# ---------------------------------------------------------------------------
# | Migration scope | Full catalog migration (same rules as `migrate` command) |
# ---------------------------------------------------------------------------

# Spec: | Migration scope | Full catalog migration ... |
# Context: every entry is migrated, not just the annotated one.
def test_migration_covers_every_entry(serve, make_vault, legacy, annotate,
                                      workdir, helpers):
    v1_vault(make_vault, legacy, ids=("e1", "e2", "e3"))
    create(annotate, serve().client, "entries", entry_id="e2")
    catalog = helpers.read_catalog(workdir)
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1", "e2", "e3"]
    for entry in catalog["episodes"]:
        assert "removed" in entry
        assert isinstance(entry["annotations"], list)


# Spec: | Migration scope | Full catalog migration (same rules as `migrate`) |
# Context: a migrated v1 catalog carries the v3 category arrays and no v1 keys.
def test_migrated_catalog_has_v3_shape(serve, make_vault, legacy, annotate,
                                       workdir, helpers):
    v1_vault(make_vault, legacy)
    create(annotate, serve().client, "entries")
    catalog = helpers.read_catalog(workdir)
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}
    assert catalog["streams"] == [] and catalog["clips"] == []


# Spec: | v1 `source_id` conversion | Same rules as `migrate` command |
def test_v1_source_id_conversion(serve, make_vault, legacy, annotate, workdir,
                                 helpers):
    v1_vault(make_vault, legacy, source_id="chan-77")
    create(annotate, serve().client, "entries")
    catalog = helpers.read_catalog(workdir)
    assert catalog["source"] == legacy.v1_source("chan-77")
    assert "source_id" not in catalog


# Spec: | v1 UNIX-epoch key conversion | Same rules as `migrate` command |
def test_v1_epoch_keys_become_iso(serve, make_vault, legacy, annotate, workdir,
                                  helpers):
    v1_vault(make_vault, legacy)
    create(annotate, serve().client, "entries")
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert list(entry["title"]) == [legacy.V1_EPOCH_ISO]
    assert entry["title"][legacy.V1_EPOCH_ISO] == "Title e1"
    for field in ("description", "views", "likes", "preview"):
        assert list(entry[field]) == [legacy.V1_EPOCH_ISO], field


# Spec: | Auto-migration timestamp | Same timestamp used for all
#   migration-added `removed` fields | (Determinism)
def test_migration_timestamp_is_shared(serve, make_vault, legacy, annotate,
                                       workdir, helpers):
    v1_vault(make_vault, legacy, ids=("e1", "e2", "e3"))
    create(annotate, serve().client, "entries")
    catalog = helpers.read_catalog(workdir)
    stamps = {key for entry in catalog["episodes"] for key in entry["removed"]}
    assert len(stamps) == 1, stamps
    stamp = stamps.pop()
    assert ISO_RE.match(stamp), stamp
    assert all(entry["removed"][stamp] is False for entry in catalog["episodes"])


# Spec: | ... | Same timestamp used for all migration-added `removed` fields |
# Context: a v2 auto-migration adds `removed` across all three categories at
# one instant.
def test_v2_migration_timestamp_is_shared(serve, make_vault, legacy, annotate,
                                          workdir, helpers):
    make_vault(legacy.v2_catalog(
        episodes=[legacy.v2_entry("e1")],
        streams=[legacy.v2_entry("s1")],
        clips=[legacy.v2_entry("c1")]))
    create(annotate, serve().client, "episodes")
    catalog = helpers.read_catalog(workdir)
    stamps = {key
              for category in ("episodes", "streams", "clips")
              for entry in catalog[category]
              for key in entry["removed"]}
    assert len(stamps) == 1, stamps


# ---------------------------------------------------------------------------
# | Backup before migration | `catalog.bak` contains the original
#   pre-migration catalog |
# ---------------------------------------------------------------------------

# Spec: | Backup before migration | `catalog.bak` contains the original
#   pre-migration catalog |
def test_backup_holds_the_pre_migration_catalog(serve, make_vault, legacy,
                                                annotate, workdir):
    vault = v1_vault(make_vault, legacy)
    before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
    create(annotate, serve().client, "entries")
    assert annotate.backup(workdir) == before


# Spec: | Single write for migration + annotation | ... backup must reflect
#   state before **both** changes |
def test_backup_precedes_both_changes(serve, make_vault, legacy, annotate,
                                      workdir):
    v1_vault(make_vault, legacy)
    create(annotate, serve().client, "entries")
    backup = annotate.backup(workdir)
    assert backup["version"] == 1
    assert "entries" in backup and "episodes" not in backup
    assert "annotations" not in backup["entries"][0]


# Spec: | Single write for migration + annotation | Migration and annotation
#   may be persisted in one write | ...
# Context: whatever the write count, the file on disk ends up migrated *and*
# annotated, and only one backup generation exists.
def test_single_write_leaves_both_changes_on_disk(serve, make_vault, legacy,
                                                  annotate, workdir, helpers):
    v1_vault(make_vault, legacy)
    create(annotate, serve().client, "entries", title="Both")
    catalog = helpers.read_catalog(workdir)
    assert catalog["version"] == 3
    assert catalog["episodes"][0]["annotations"][0]["title"] == "Both"
    assert annotate.backup(workdir)["version"] == 1


# ---------------------------------------------------------------------------
# | Auto-Migration - Category Transition |
# ---------------------------------------------------------------------------

# Spec: | Request URL category | `entries` (v1 category name) |
# Spec: | Entry lookup | Find entry by `id` in the v1 `entries` array |
def test_v1_request_uses_the_pre_migration_category(serve, make_vault, legacy,
                                                    annotate, workdir):
    v1_vault(make_vault, legacy, ids=("e1", "e2"))
    response = create(annotate, serve().client, "entries", entry_id="e2",
                      title="on e2")
    assert response.status in REDIRECTS, response.body[:400]
    assert annotate.only(workdir, "vault", "e2", "episodes")["title"] == "on e2"
    assert annotate.stored(workdir, "vault", "e1", "episodes") == []


# Spec: | Post-migration location | Entry is in `episodes` after migration |
def test_entry_lands_in_episodes(serve, make_vault, legacy, annotate, workdir,
                                 helpers):
    v1_vault(make_vault, legacy)
    create(annotate, serve().client, "entries")
    catalog = helpers.read_catalog(workdir)
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1"]
    assert "entries" not in catalog


# Spec: | Redirect after success | Redirect uses post-migration category
#   (`episodes`) |
# Spec: | Redirect after v1 annotation | Uses `episodes`, not `entries` |
def test_redirect_uses_episodes(serve, make_vault, legacy, annotate):
    v1_vault(make_vault, legacy)
    response = create(annotate, serve().client, "entries")
    assert annotate.target(response) == "/catalog/vault/episodes/e1"


# Spec: | Redirect after success | ... | + | Create-success redirect value |
#   Integer whole seconds |
def test_v1_redirect_still_carries_the_timecode(serve, make_vault, legacy,
                                                annotate):
    v1_vault(make_vault, legacy)
    response = create(annotate, serve().client, "entries", timecode="1:30")
    assert annotate.timecode(response) == "90"


# Spec: | Redirect after success | ... post-migration category ... |
# Context: following the redirect reaches a live v3 detail page that shows the
# new annotation.
def test_v1_redirect_is_followable(serve, make_vault, legacy, annotate):
    v1_vault(make_vault, legacy)
    response = create(annotate, serve().client, "entries", title="Landed",
                      follow=True)
    assert response.status == 200, response.status
    assert "Landed" in annotate.text(response.body)


# Spec: | Subsequent requests | Must use `episodes` (v1 `entries` route is
#   retired after migration) |
def test_subsequent_annotation_uses_episodes(serve, make_vault, legacy,
                                             annotate, workdir):
    v1_vault(make_vault, legacy)
    client = serve().client
    create(annotate, client, "entries", title="first")
    response = create(annotate, client, "episodes", title="second")
    assert response.status in REDIRECTS, response.body[:400]
    titles = [item["title"]
              for item in annotate.stored(workdir, "vault", "e1", "episodes")]
    assert titles == ["first", "second"]


# Spec: | Post auto-migration viewer routing | Vault now serves as v3; valid
#   categories become `episodes`, `streams`, `clips` ... |
def test_v3_categories_are_valid_after_migration(serve, make_vault, legacy,
                                                 annotate, detail):
    v1_vault(make_vault, legacy)
    client = serve().client
    create(annotate, client, "entries")
    for category in ("episodes", "streams", "clips"):
        response = client.get(detail.listing("vault", category))
        assert response.status == 200, (category, response.status)


# Spec: | ... | v1 `entries` category is no longer valid |
# Spec: | Retired GET behavior | Later `GET` requests to the retired v1
#   `entries` route may redirect to canonical v3 viewer routes or return `404` |
def test_retired_entries_route_after_migration(serve, make_vault, legacy,
                                               annotate, detail):
    v1_vault(make_vault, legacy)
    client = serve().client
    create(annotate, client, "entries")
    response = client.get(detail.listing("vault", "entries"))
    assert response.status == 404 or response.status in REDIRECTS, \
        response.status
    if response.status in REDIRECTS:
        assert "/entries" not in (response.location or ""), response.location


# Spec: | Retired GET behavior | ... | (detail route)
def test_retired_entries_detail_route_after_migration(serve, make_vault,
                                                      legacy, annotate,
                                                      detail):
    v1_vault(make_vault, legacy)
    client = serve().client
    create(annotate, client, "entries")
    response = client.get(detail.path("vault", "entries", "e1"))
    assert response.status == 404 or response.status in REDIRECTS, \
        response.status


# Spec: | Post auto-migration viewer routing | Vault now serves as v3 ... |
# Context: the default category redirect follows the new version.
def test_default_category_after_migration(serve, make_vault, legacy, annotate):
    v1_vault(make_vault, legacy)
    client = serve().client
    create(annotate, client, "entries")
    response = client.get("/catalog/vault")
    assert response.status in REDIRECTS, response.status
    assert response.location.endswith("/catalog/vault/episodes"), \
        response.location


# Spec: Pristine v1 and v2 catalogs do not define `annotations`. As a result,
# `PATCH`/`DELETE` on legacy vaults are only meaningful after auto-migration
# has produced an entry that already contains annotations, such as after a
# prior successful `POST` in the same migrated vault.
def test_patch_after_a_v1_post(serve, make_vault, legacy, annotate, workdir):
    v1_vault(make_vault, legacy)
    client = serve().client
    create(annotate, client, "entries", title="before")
    annotation_id = annotate.only(workdir, "vault", "e1", "episodes")["id"]
    response = annotate.update(client, "vault", "episodes", "e1",
                               {"id": annotation_id, "title": "after"})
    assert response.status in REDIRECTS, response.body[:400]
    assert annotate.only(workdir, "vault", "e1", "episodes")["title"] == "after"


# Spec: ... `PATCH`/`DELETE` on legacy vaults are only meaningful after
# auto-migration ... (delete leg)
def test_delete_after_a_v1_post(serve, make_vault, legacy, annotate, workdir):
    v1_vault(make_vault, legacy)
    client = serve().client
    create(annotate, client, "entries")
    annotation_id = annotate.only(workdir, "vault", "e1", "episodes")["id"]
    response = annotate.remove(client, "vault", "episodes", "e1",
                               {"id": annotation_id})
    assert response.status in REDIRECTS, response.body[:400]
    assert annotate.stored(workdir, "vault", "e1", "episodes") == []


# Spec: Pristine v1 and v2 catalogs do not define `annotations`.
# Context: T79 - a `PATCH` against a pristine v1 vault cannot find the
# annotation, so it is a `404` and the vault is left as it was.
def test_patch_on_a_pristine_v1_vault(serve, make_vault, legacy, annotate,
                                      workdir, helpers):
    v1_vault(make_vault, legacy)
    response = annotate.update(serve().client, "vault", "entries", "e1",
                               {"id": "a1", "title": "x"})
    assert response.status == 404, response.status
    assert helpers.read_catalog(workdir)["version"] == 1
    assert not annotate.has_backup(workdir)


# Spec: Pristine v1 and v2 catalogs do not define `annotations`.
# Context: T79 - and the same for `DELETE` on a pristine v2 vault.
def test_delete_on_a_pristine_v2_vault(serve, make_vault, legacy, annotate,
                                       workdir, helpers):
    v2_vault(make_vault, legacy)
    response = annotate.remove(serve().client, "vault", "episodes", "e1",
                               {"id": "a1"})
    assert response.status == 404, response.status
    assert helpers.read_catalog(workdir)["version"] == 2
    assert not annotate.has_backup(workdir)


# Spec: | Request URL category | `entries` (v1 category name) |
# Context: T71 - the post-migration name is not a valid category on a vault
# that is still v1.
def test_episodes_category_on_a_still_v1_vault(serve, make_vault, legacy,
                                               annotate, workdir, helpers):
    v1_vault(make_vault, legacy)
    response = create(annotate, serve().client, "episodes")
    assert response.status == 404, response.status
    assert helpers.read_catalog(workdir)["version"] == 1


# Spec: | Migration failure during auto-migration | HTTP `500` with error
#   message; original catalog unchanged |
def test_migration_failure_is_500(serve, make_vault, legacy, annotate):
    broken = legacy.v1_entry("e1")
    broken["title"] = {"not-an-epoch": "Title e1"}
    make_vault(legacy.v1_catalog([broken]))
    response = create(annotate, serve().client, "entries")
    assert response.status == 500, response.status


# Spec: | Migration failure during auto-migration | ... original catalog
#   unchanged |
def test_migration_failure_leaves_the_catalog(serve, make_vault, legacy,
                                              annotate, workdir, snapshot):
    broken = legacy.v1_entry("e1")
    broken["title"] = {"not-an-epoch": "Title e1"}
    vault = make_vault(legacy.v1_catalog([broken]))
    before = snapshot(vault)
    create(annotate, serve().client, "entries")
    assert snapshot(vault) == before


# Spec: | Migration failure during auto-migration | HTTP `500` with error
#   message ... | + | Any error response | ... no raw traceback or stack trace |
def test_migration_failure_has_a_message_and_no_traceback(serve, make_vault,
                                                          legacy, annotate):
    broken = legacy.v1_entry("e1")
    broken["views"] = {"1718444400": "not an integer"}
    make_vault(legacy.v1_catalog([broken]))
    response = create(annotate, serve().client, "entries")
    assert response.status == 500, response.status
    assert response.body.strip(), "empty error body"
    assert "Traceback" not in response.body
    assert "File \"" not in response.body


# Spec: | Migration failure during auto-migration | ... |
# Context: a v2 catalog whose category array is not an array fails the same way.
def test_v2_migration_failure_is_500(serve, make_vault, legacy, annotate,
                                     workdir, helpers):
    catalog = legacy.v2_catalog(episodes=[legacy.v2_entry("e1")])
    catalog["clips"] = {"not": "an array"}
    make_vault(catalog)
    response = create(annotate, serve().client, "episodes")
    assert response.status == 500, response.status
    assert helpers.read_catalog(workdir)["version"] == 2
