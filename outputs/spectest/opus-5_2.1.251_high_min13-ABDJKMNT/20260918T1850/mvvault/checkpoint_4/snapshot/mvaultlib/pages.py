"""The viewer's HTML: the landing page, a category listing, and error pages."""

from html import escape

from .links import category_path, entry_path

#: Page styling, deliberately free of any state name, so that a word such as
#: "downloaded" appears on a page only where an entry is really in that state.
STYLE = (
    "body{font-family:system-ui,sans-serif;margin:2rem;max-width:52rem;color:#222}"
    "h1{font-size:1.4rem}"
    "ul{list-style:none;padding:0}"
    "li{padding:.35rem .5rem;border-bottom:1px solid #eee}"
    "nav a{margin-right:1rem}"
    ".badge{font-size:.78rem;padding:.05rem .45rem;border-radius:.6rem;margin-left:.5rem}"
    ".notice{background:#fdecea;padding:.5rem .75rem;border-radius:.4rem}"
)

#: Inline styling for the states a listing row can be in.
FETCHED_BADGE = "background:#e6f4ea;color:#14532d"
PENDING_BADGE = "background:#eeeeee;color:#555555"
GONE_BADGE = "background:#fdecea;color:#7f1d1d"
GONE_ROW = "text-decoration:line-through"
CURRENT_ROW = "background:#fff8c4;border-left:4px solid #e2b93b"


def landing_page(recent, missing=None):
    """The landing page: the vault-name form, plus where this browser has been.

    `recent` pairs each remembered vault with the path its link opens, and
    `missing` names a vault the viewer was asked for and could not find.
    """
    return _document(
        "mvault viewer",
        [
            "<h1>mvault viewer</h1>",
            _missing_notice(missing),
            _vault_form(),
            _recent_list(recent),
        ],
    )


def category_page(listing, highlight=None):
    """One category listing, with the entry `highlight` names surfaced."""
    heading = f"{listing.name} / {listing.category}"
    return _document(
        f"{heading} - mvault",
        [
            f'<p><a href="/">mvault viewer</a> - catalog version {listing.version}</p>',
            f"<h1>{escape(heading)}</h1>",
            _category_nav(listing),
            _entry_list(listing, highlight),
        ],
    )


def error_page(message):
    """The page any request that cannot be answered gets instead."""
    return _document(
        "mvault viewer",
        [
            "<h1>mvault viewer</h1>",
            f'<p class="notice">{escape(message)}</p>',
            '<p><a href="/">Back to the vault list</a></p>',
        ],
    )


def _vault_form():
    """The form that takes a vault name and posts it back to the landing page."""
    return (
        '<form method="post" action="/">\n'
        '<label for="catalog">Vault name</label>\n'
        '<input id="catalog" name="catalog" type="text" autofocus>\n'
        '<button type="submit">Open</button>\n'
        "</form>"
    )


def _missing_notice(missing):
    """Says which vault the viewer was sent to and could not find."""
    if not missing:
        return ""
    return f'<p class="notice">Vault <code>{escape(missing)}</code> was not found.</p>'


def _recent_list(recent):
    """The recently visited vaults, most recent first; absent when there are none."""
    if not recent:
        return ""
    items = [
        f'<li><a href="{path}">{escape(name)}</a></li>' for name, path in recent
    ]
    return "<h2>Recent vaults</h2>\n<ul>\n" + "\n".join(items) + "\n</ul>"


def _category_nav(listing):
    """Links to the other categories this vault's version has."""
    links = [
        f'<a href="{category_path(listing.name, category)}">{escape(category)}</a>'
        for category in listing.categories
    ]
    return f"<nav>{''.join(links)}</nav>"


def _entry_list(listing, highlight):
    """The category's entries, in stored order."""
    if not listing.rows:
        return "<p>This category has no entries.</p>"
    rows = [_entry_row(listing, row, row.entry_id == highlight) for row in listing.rows]
    return "<ul>\n" + "\n".join(rows) + "\n</ul>"


def _entry_row(listing, row, highlighted):
    """One entry: its link, whether its media is here, and whether it is gone."""
    classes = ["entry", "downloaded" if row.downloaded else "pending"]
    badges = [
        _badge("downloaded", FETCHED_BADGE)
        if row.downloaded
        else _badge("not fetched", PENDING_BADGE)
    ]
    styles = []
    if row.removed:
        classes.append("removed")
        badges.append(_badge("removed", GONE_BADGE))
        styles.append(GONE_ROW)
    if highlighted:
        classes.append("current")
        styles.append(CURRENT_ROW)

    target = entry_path(listing.name, listing.category, row.entry_id)
    style = f' style="{";".join(styles)}"' if styles else ""
    return (
        f'<li class="{" ".join(classes)}"{style}>'
        f'<a href="{target}">{escape(row.title)}</a>{"".join(badges)}</li>'
    )


def _badge(text, style):
    return f'<span class="badge" style="{style}">{text}</span>'


def _document(title, blocks):
    """A complete HTML document from the blocks that have something to say."""
    body = "\n".join(block for block in blocks if block)
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )
