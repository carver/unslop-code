"""Helpers for the entry-detail and `/vault` static-endpoint spec tests.

The spec leaves the chart payload's container and key names unspecified
("Payload container and key names | Unspecified as long as the payload
remains machine-readable"), so the helpers here locate and normalize the
embedded data instead of assuming one shape.
"""
import html
import json
import os
import re

from conftest import media_dir, previews_dir, write_file, write_vault

SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
EPOCH_RE = re.compile(r"^-?\d+$")


def embedded_payloads(text):
    """Every machine-readable JSON payload embedded in the HTML document."""
    payloads = []
    for attrs, body in SCRIPT_RE.findall(text):
        if "json" not in attrs.lower():
            continue
        try:
            payloads.append(json.loads(html.unescape(body.strip())))
        except ValueError:
            continue
    return payloads


def _candidates(node, field):
    """Every value stored under a key named `field`, at any depth."""
    out = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.lower() == field:
                out.append(value)
            out.extend(_candidates(value, field))
    elif isinstance(node, list):
        for item in node:
            out.extend(_candidates(item, field))
    return out


def _pair_from_mapping(item):
    """`{"timestamp": ..., "value": ...}` in whatever key names were used."""
    stamp_keys = [k for k, v in item.items()
                  if isinstance(v, str) and ISO_RE.match(v)]
    if len(stamp_keys) != 1:
        return None
    stamp = stamp_keys[0]
    rest = [k for k in item if k != stamp]
    if len(rest) != 1:
        return None
    return (item[stamp], item[rest[0]])


def normalize_points(node):
    """Reduce a chart payload to `[(timestamp, value), ...]`, or None."""
    if isinstance(node, dict):
        if node and all(isinstance(k, str) and ISO_RE.match(k) for k in node):
            return [(k, node[k]) for k in node]
        for value in node.values():
            pairs = normalize_points(value)
            if pairs is not None:
                return pairs
        return None
    if not isinstance(node, list):
        return None
    pairs = []
    for item in node:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            pairs.append((item[0], item[1]))
        elif isinstance(item, dict):
            pair = _pair_from_mapping(item)
            if pair is None:
                return None
            pairs.append(pair)
        else:
            return None
    return pairs


def chart_points(text, field):
    """`[(timestamp, value), ...]` for `views` or `likes`, or None if absent.

    Returns the longest candidate so that a payload which also carries a
    scalar current value alongside the series is still understood.
    """
    best = None
    for payload in embedded_payloads(text):
        for candidate in _candidates(payload, field):
            pairs = normalize_points(candidate)
            if pairs and (best is None or len(pairs) > len(best)):
                best = pairs
    return best


def build_vault(tmp_path, catalog, name="vault", media=(), previews=()):
    """Write a catalog plus any archived media/preview files beside it."""
    write_vault(tmp_path, catalog, name)
    for filename in media:
        write_file(os.path.join(media_dir(tmp_path, name), filename),
                   b"media-bytes-" + filename.encode("utf-8"))
    for filename in previews:
        write_file(os.path.join(previews_dir(tmp_path, name), filename),
                   b"\xff\xd8\xff-preview-" + filename.encode("utf-8"))
    return name


def detail(client, name, category, eid):
    return client.get("/catalog/%s/%s/%s" % (name, category, eid))


def history(pairs):
    """A history object built from `(key, value)` pairs."""
    return {key: value for key, value in pairs}
