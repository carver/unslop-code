"""Builders and parsers shared by the `digest` spec tests."""
import os

# Deterministic ISO history keys (v2/v3) in ascending order.
K1 = "2024-01-01T00:00:00"
K2 = "2024-02-01T00:00:00"
K3 = "2024-03-01T00:00:00"

# Matching UNIX-epoch keys (v1), same instants.
E1 = "1704067200"   # 2024-01-01T00:00:00Z
E2 = "1706745600"   # 2024-02-01T00:00:00Z
E3 = "1709251200"   # 2024-03-01T00:00:00Z

TRACKED = ("title", "description", "views", "likes", "preview")


def _hist(value, key):
    return value if isinstance(value, dict) else {key: value}


def v3_entry(id="e1", published="2024-05-01T12:00:00", title=None,
             description=None, views=None, likes=None, preview=None,
             removed=None, key=K1):
    """A v3 entry; each tracked field accepts a full history dict."""
    return {
        "id": id,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": _hist("Title %s" % id if title is None else title, key),
        "description": _hist("Desc" if description is None else description, key),
        "views": _hist(10 if views is None else views, key),
        "likes": _hist(1 if likes is None else likes, key),
        "preview": _hist("hash0" if preview is None else preview, key),
        "removed": _hist(False if removed is None else removed, key),
        "annotations": [],
    }


def legacy_entry(id="e1", published="2024-05-01T12:00:00", title=None,
                 description=None, views=None, likes=None, preview=None,
                 key=K1):
    """A v1/v2 entry: the five source-tracked fields, no `removed`."""
    return {
        "id": id,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": _hist("Title %s" % id if title is None else title, key),
        "description": _hist("Desc" if description is None else description, key),
        "views": _hist(10 if views is None else views, key),
        "likes": _hist(1 if likes is None else likes, key),
        "preview": _hist("hash0" if preview is None else preview, key),
    }


def v1_entry(id="e1", **kwargs):
    """A v1 entry: the legacy shape with UNIX-epoch history keys."""
    kwargs.setdefault("key", E1)
    return legacy_entry(id=id, **kwargs)


def v3(source="https://media.example.com/channel/chan42", episodes=(),
       streams=(), clips=()):
    return {"version": 3, "source": source, "episodes": list(episodes),
            "streams": list(streams), "clips": list(clips)}


def v2(source="https://media.example.com/channel/chan42", episodes=(),
       streams=(), clips=()):
    return {"version": 2, "source": source, "episodes": list(episodes),
            "streams": list(streams), "clips": list(clips)}


def v1(source_id="chan42", entries=()):
    return {"version": 1, "source_id": source_id, "entries": list(entries)}


# --------------------------------------------------------------------------
# Output parsing
# --------------------------------------------------------------------------
def body_lines(stdout):
    """Everything above the trailing metadata line."""
    lines = stdout.rstrip("\n").split("\n")
    assert lines, stdout
    return lines[:-1]


def trailing_line(stdout):
    return stdout.rstrip("\n").split("\n")[-1]


def sections(stdout):
    """Parse the digest body into `{category: {group: [entry text, ...]}}`.

    Insertion order is preserved, so callers can assert on ordering.
    """
    result = {}
    category = group = None
    for line in body_lines(stdout):
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            if line.rstrip().endswith(":"):
                category = line.rstrip()[:-1]
                result[category] = {}
                group = None
            continue
        text = line.strip()
        if text.startswith("- "):
            assert category is not None and group is not None, stdout
            result[category][group].append(text[2:])
        elif text.endswith(":"):
            group = text[:-1]
            result[category][group] = []
    return result


def entry_titles(stdout, category, group):
    return sections(stdout).get(category, {}).get(group, [])
