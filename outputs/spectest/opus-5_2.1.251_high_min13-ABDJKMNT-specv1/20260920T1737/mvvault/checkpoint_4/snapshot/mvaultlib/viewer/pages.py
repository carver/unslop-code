"""HTML for the viewer's two pages: the landing page and a category listing."""

from html import escape

from mvaultlib.viewer.links import catalog_path

STYLE = """
body { font-family: system-ui, sans-serif; max-width: 48rem; margin: 2rem auto; }
h1 { font-size: 1.4rem; }
nav a { margin-right: .75rem; }
ul.entries { list-style: none; padding: 0; }
li.entry { padding: .35rem .5rem; border-left: 4px solid #2f6feb; }
li.pending { border-left-color: #c9ced6; }
li.pending a { color: #5b6270; }
li.removed { border-left-color: #b3261e; text-decoration: line-through; }
li.current { background: #fff6d5; }
span.badge { font-size: .8rem; color: #5b6270; margin-left: .5rem; }
p.notice { background: #fdeceb; border-left: 4px solid #b3261e; padding: .5rem; }
"""


def page(title, body):
    """Wrap rendered body markup in the viewer's minimal HTML document."""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def landing_page(recent, missing=None):
    """The vault-name form, the vault-not-found notice and the recent vaults.

    `recent` holds `(name, path)` pairs, newest first, where each path is the
    vault's resolved default category page.
    """
    sections = ["<h1>mvault viewer</h1>"]
    if missing is not None:
        sections.append(f'<p class="notice">Vault "{escape(missing)}" was not found.</p>')
    sections.append(
        '<form method="post" action="/">\n'
        '<label for="catalog">Vault name</label>\n'
        '<input id="catalog" name="catalog" autofocus>\n'
        '<button type="submit">Open</button>\n</form>'
    )
    sections.append(_recent_section(recent))
    return page("mvault viewer", "\n".join(section for section in sections if section))


def category_page(name, view, group, entries, current_id=None):
    """One category listing: its entries in catalog order, states marked.

    `current_id` is the entry an entry link pointed at, which is surfaced among
    the others rather than shown on a page of its own.
    """
    rows = "\n".join(_entry_row(name, group.category, entry, current_id) for entry in entries)
    body = (
        f"<h1>{escape(name)} &mdash; {escape(group.label)}</h1>\n"
        f'<p>Catalog version {view.version}. <a href="/">All vaults</a></p>\n'
        f"{_category_nav(name, view, group.category)}\n"
        f'<ul class="entries">\n{rows}\n</ul>'
    )
    return page(f"{name} - {group.label}", body)


def _recent_section(recent):
    """The recently visited vaults, or nothing at all when none were visited."""
    if not recent:
        return ""
    links = "\n".join(
        f'<li><a href="{escape(path)}">{escape(name)}</a></li>' for name, path in recent
    )
    return f"<h2>Recent vaults</h2>\n<ul>\n{links}\n</ul>"


def _category_nav(name, view, current):
    """Links to the sibling categories this vault version offers."""
    links = " ".join(
        f'<a href="{catalog_path(name, group.category)}">{escape(group.label)}</a>'
        if group.category != current
        else f"<strong>{escape(group.label)}</strong>"
        for group in view.groups
    )
    return f"<nav>{links}</nav>"


def _entry_row(name, category, entry, current_id):
    """One entry, on a single line, carrying its state in classes and badges."""
    classes = ["entry", "downloaded" if entry.downloaded else "pending"]
    badges = ["downloaded" if entry.downloaded else "not downloaded"]
    if entry.removed:
        classes.append("removed")
        badges.append("removed")
    if entry.entry_id == current_id:
        classes.append("current")
    link = catalog_path(name, category, entry.entry_id)
    marks = "".join(f'<span class="badge">{badge}</span>' for badge in badges)
    return (
        f'<li class="{" ".join(classes)}" data-entry="{escape(entry.entry_id)}">'
        f'<a href="{link}">{escape(entry.title)}</a>{marks}</li>'
    )
