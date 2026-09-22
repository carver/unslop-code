"""Spec section: `sync` Post-Summary (and its Determinism row)."""
import re

from conftest import entry, lines, payload, v2_catalog, v2_entry, write_vault


def summary_line(text):
    found = [ln for ln in lines(text) if "added" in ln.lower()]
    assert len(found) == 1, text
    return found[0]


def counts(text):
    """The added/removed/updated numbers reported after a sync."""
    line = summary_line(text)
    out = {}
    for key in ("added", "removed", "updated"):
        match = re.search(key + r"\D*(\d+)", line, re.IGNORECASE)
        assert match, (key, line)
        out[key] = int(match.group(1))
    return out


# --- Phrase: "| Trigger | Successful `sync` run that includes metadata
#     phase |" + "| Output stream | stdout |"
def test_successful_sync_prints_a_summary_to_stdout(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault", "--skip-download")
    assert result.returncode == 0, result
    assert result.stdout.strip(), result


# --- Phrase: "| Counts reported | Added, removed, updated |"
def test_summary_reports_all_three_counts(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault", "--skip-download")
    assert set(counts(result.stdout)) == {"added", "removed", "updated"}


def test_first_sync_counts_additions(run, source, vault):
    source.set_payload(
        payload(episodes=[entry("e1"), entry("e2")], clips=[entry("c1")])
    )
    result = run("sync", "vault", "--skip-download")
    assert counts(result.stdout) == {"added": 3, "removed": 0, "updated": 0}


# --- Phrase: "| Counts reported | Added, removed, updated |" (context: an
#     unchanged re-sync reports zeroes)
def test_unchanged_resync_reports_zero_counts(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    result = run("sync", "vault", "--skip-download")
    assert counts(result.stdout) == {"added": 0, "removed": 0, "updated": 0}


def test_changed_field_counts_as_an_update(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1", views=1)]))
    run("sync", "vault", "--skip-download")
    source.set_payload(payload(episodes=[entry("e1", views=2)]))
    result = run("sync", "vault", "--skip-download")
    assert counts(result.stdout) == {"added": 0, "removed": 0, "updated": 1}


def test_vanished_entry_counts_as_a_removal(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1"), entry("e2")]))
    run("sync", "vault", "--skip-download")
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault", "--skip-download")
    assert counts(result.stdout) == {"added": 0, "removed": 1, "updated": 0}


def test_mixed_run_reports_each_count(run, source, vault):
    source.set_payload(
        payload(episodes=[entry("gone"), entry("changing", views=1)])
    )
    run("sync", "vault", "--skip-download")
    source.set_payload(
        payload(episodes=[entry("changing", views=2), entry("fresh")])
    )
    result = run("sync", "vault", "--skip-download")
    assert counts(result.stdout) == {"added": 1, "removed": 1, "updated": 1}


# --- Phrase: "Each entry may appear once." applied to the counts (see
#     AMBIGUITIES T29)
def test_removed_entry_with_other_changes_counts_once(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1", title="First")]))
    run("sync", "vault", "--skip-download")
    source.set_payload(payload())
    result = run("sync", "vault", "--skip-download")
    assert counts(result.stdout) == {"added": 0, "removed": 1, "updated": 0}


# --- Phrase: "| Trigger | Successful `sync` run that includes metadata
#     phase |" (context: a reappearance is a tracked-field change)
def test_reappearing_entry_counts_as_an_update(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    source.set_payload(payload())
    run("sync", "vault", "--skip-download")
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault", "--skip-download")
    assert counts(result.stdout) == {"added": 0, "removed": 0, "updated": 1}


# --- Phrase: "| Trigger | Successful `sync` run that includes metadata
#     phase |" (context: `--skip-metadata` has no metadata phase)
def test_skip_metadata_prints_no_summary(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    result = run("sync", "vault", "--skip-metadata")
    assert result.returncode == 0, result
    assert "added" not in result.stdout.lower(), result


# --- Phrase: "| Trigger | Successful `sync` run that includes metadata
#     phase |" (context: `--skip-download` keeps the metadata phase, T40)
def test_skip_download_still_prints_the_summary(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault", "--skip-download")
    assert counts(result.stdout)["added"] == 1


# --- Phrase: "| Post-sync counts | Deterministic for the same vault state and
#     source metadata |"
def test_summary_is_deterministic_for_the_same_state(run, source, tmp_path):
    payload_obj = payload(episodes=[entry("e1"), entry("e2")])
    first = None
    for name in ("one", "two"):
        run("init", name, source.url)
        source.set_payload(payload_obj)
        out = summary_line(run("sync", name, "--skip-download").stdout)
        if first is None:
            first = out
        else:
            assert out == first


# --- Phrase: "| Trigger | Successful `sync` run ... |" (context: a failed
#     source fetch aborts, so no summary is printed)
def test_failed_fetch_prints_no_summary(run, source, vault):
    source.set_raw("not json", status=500)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert "added" not in result.stdout.lower(), result


# --- Phrase: "| Trigger | Successful `sync` run that includes metadata phase
#     |" (context: download failures do not suppress the summary)
def test_download_failures_do_not_suppress_the_summary(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault")
    assert result.returncode == 0, result
    assert counts(result.stdout)["added"] == 1


# --- Phrase: "| Trigger | Successful `sync` run that includes metadata phase
#     |" (context: a legacy vault's first sync migrates and still summarizes)
def test_legacy_vault_sync_prints_a_summary(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     episodes=[v2_entry("old")]))
    source.set_payload(payload(episodes=[entry("old"), entry("new")]))
    result = run("sync", "vault", "--skip-download")
    assert result.returncode == 0, result
    assert counts(result.stdout)["added"] == 1
