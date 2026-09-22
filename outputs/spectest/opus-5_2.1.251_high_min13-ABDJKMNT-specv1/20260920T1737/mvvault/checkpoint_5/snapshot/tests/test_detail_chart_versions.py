"""Spec sections: Chart Data -- Version-Aware Timestamp Normalization, and
Chart Data -- Ordering Across Versions."""

import re

import pytest
from conftest import chart_points, point_pairs
from detail_fixtures import (
    EPOCH_NEW,
    EPOCH_NEW_AS_ISO,
    EPOCH_OLD,
    EPOCH_OLD_AS_ISO,
    ISO_NEW,
    ISO_OLD,
    VERSION_CASES,
    v1_vault,
    v2_vault,
    v3_vault,
)

ISO_8601 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def pairs(viewer, field, category="episodes", entry_id="e1"):
    body = viewer.client.get(f"/catalog/demo/{category}/{entry_id}").body
    return point_pairs(chart_points(body, field))


# Phrase: "Chart data must present timestamps in a **uniform format** regardless
# of vault version. The output timestamp format ... is ISO 8601
# (`YYYY-MM-DDTHH:MM:SS`)."
@pytest.mark.parametrize("field", ["views", "likes"])
@pytest.mark.parametrize("build, category, entry_id", VERSION_CASES)
def test_every_version_emits_iso_8601_timestamps(viewer, tmp_path, build, category, entry_id, field):
    build(tmp_path)

    stamps = [stamp for stamp, _ in pairs(viewer, field, category, entry_id)]

    assert stamps, "no chart points were embedded"
    assert all(ISO_8601.match(stamp) for stamp in stamps), stamps


# Phrase: "| v1 | UNIX-epoch string (e.g., `\"1718444400\"`) | Convert to ISO
# 8601 UTC |".
def test_v1_epoch_keys_convert_to_iso_8601_utc(viewer, tmp_path):
    v1_vault(tmp_path)

    assert pairs(viewer, "views", "entries") == [(EPOCH_OLD_AS_ISO, 100), (EPOCH_NEW_AS_ISO, 250)]


# Phrase: "| Chart output timestamps | Always ISO 8601 regardless of vault
# version |" -- the raw epoch text never reaches the payload.
def test_v1_raw_epoch_text_is_not_emitted(viewer, tmp_path):
    v1_vault(tmp_path)

    stamps = [stamp for stamp, _ in pairs(viewer, "views", "entries")]

    assert EPOCH_OLD not in stamps
    assert EPOCH_NEW not in stamps


# Phrase: "| v2 | ISO 8601 string | Pass through |".
def test_v2_iso_keys_pass_through(viewer, tmp_path):
    v2_vault(tmp_path)

    assert pairs(viewer, "views") == [(ISO_OLD, 100), (ISO_NEW, 250)]


# Phrase: "| v3 | ISO 8601 string | Pass through |".
def test_v3_iso_keys_pass_through(viewer, tmp_path):
    v3_vault(tmp_path)

    assert pairs(viewer, "views") == [(ISO_OLD, 100), (ISO_NEW, 250)]


# Phrase: "| v1 | Numeric comparison of UNIX-epoch string keys |" and
# "| v1 chart ordering | By numeric epoch value, not lexicographic |" --
# lexicographically `999999999` sorts after `1718444400`.
@pytest.mark.parametrize("field, values", [("views", [100, 250]), ("likes", [7, None])])
def test_v1_orders_points_numerically(viewer, tmp_path, field, values):
    v1_vault(tmp_path)

    assert pairs(viewer, field, "entries") == [
        (EPOCH_OLD_AS_ISO, values[0]),
        (EPOCH_NEW_AS_ISO, values[1]),
    ]


# Phrase: "| v2 | Lexicographic comparison of ISO 8601 string keys |".
def test_v2_orders_points_lexicographically(viewer, tmp_path):
    v2_vault(tmp_path)

    assert [stamp for stamp, _ in pairs(viewer, "likes")] == [ISO_OLD, ISO_NEW]


# Phrase: "| v3 | Lexicographic comparison of ISO 8601 string keys |".
def test_v3_orders_points_lexicographically(viewer, tmp_path):
    v3_vault(tmp_path)

    assert [stamp for stamp, _ in pairs(viewer, "likes")] == [ISO_OLD, ISO_NEW]
