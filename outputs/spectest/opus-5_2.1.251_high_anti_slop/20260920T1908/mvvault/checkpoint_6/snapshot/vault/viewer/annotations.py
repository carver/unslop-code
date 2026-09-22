"""The annotations an entry's page shows, and the forms that edit them.

Stored annotations are listed in the order they were created, each one seeking
the entry's player to the moment it marks. The forms below them send the
entry's own address the JSON its annotation routes read, so the page edits a
vault through the same routes anything else would, and follows the redirect
that answers to see the result.
"""

from html import escape

from ..annotations import Annotation, format_timecode

STYLE = """
.annotations { margin: 2rem 0; }
.notes { list-style: none; padding: 0; }
.note { border-bottom: 1px solid #e4e4e4; padding: .5rem .25rem; }
.note-title { font-weight: 600; }
.note-body { margin: .35rem 0 0; }
.note form { display: inline; margin: 0; }
.note button, .seek { font-size: .8rem; padding: .15rem .5rem; }
.seek { font-variant-numeric: tabular-nums; margin-right: .5rem; }
.note details { display: inline; }
.note summary { display: inline; cursor: pointer; font-size: .8rem; margin: 0 .5rem; }
.new-note label { display: block; margin: .35rem 0; }
.new-note input { width: 20rem; max-width: 100%; }
.failed:empty { display: none; }
"""

SCRIPT = """
const player = document.querySelector('.assets video');
const start = new URLSearchParams(location.search).get('timecode');

function seek(seconds) {
  if (!player) return;
  if (player.readyState) player.currentTime = seconds;
  else player.addEventListener('loadedmetadata', () => { player.currentTime = seconds; },
                               { once: true });
}

if (start) seek(Number(start));

document.querySelectorAll('.annotations .seek').forEach((button) => {
  button.addEventListener('click', () => seek(Number(button.dataset.seconds)));
});

document.querySelectorAll('.annotations form').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const fields = {};
    new FormData(form).forEach((value, name) => { if (value !== '') fields[name] = value; });
    const answer = await fetch(location.pathname, {
      method: form.dataset.method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    });
    if (answer.redirected) location.assign(answer.url);
    else document.querySelector('.annotations .failed').textContent =
      `The vault refused that annotation (${answer.status}).`;
  });
});
"""


def annotation_section(annotations: tuple[Annotation, ...]) -> str:
    """The annotations of one entry, the forms that edit them and the script behind both."""
    return (
        '<section class="annotations">\n<h2>Annotations</h2>\n'
        f"{_note_list(annotations)}\n{_create_form()}\n"
        '<p class="notice failed"></p>\n'
        f"<script>{SCRIPT}</script>\n</section>"
    )


def _note_list(annotations: tuple[Annotation, ...]) -> str:
    if not annotations:
        return '<p class="meta">No annotations are stored for this entry.</p>'
    return f'<ol class="notes">\n{"".join(_note(note) for note in annotations)}\n</ol>'


def _note(note: Annotation) -> str:
    """One annotation: where it points, what it says, and how to change it."""
    body = f'<p class="note-body">{escape(note.body)}</p>' if note.body else ""
    return (
        f'<li class="note" id="annotation-{escape(note.annotation_id)}">'
        f'<button type="button" class="seek" data-seconds="{note.timecode}">'
        f"{format_timecode(note.timecode)}</button>"
        f'<span class="note-title">{escape(note.title)}</span>'
        f"{_edit_form(note)}{_delete_form(note)}{body}"
        "</li>\n"
    )


def _edit_form(note: Annotation) -> str:
    """The form that sends a ``PATCH``, starting from what the annotation says now."""
    return (
        "<details><summary>Edit</summary>"
        f'<form data-method="PATCH">{_id_field(note)}'
        f'<input name="title" aria-label="Title" value="{escape(note.title)}">'
        f'<input name="body" aria-label="Body" value="{escape(note.body or "")}">'
        "<button type=\"submit\">Save</button></form></details>"
    )


def _delete_form(note: Annotation) -> str:
    """The form that sends a ``DELETE``."""
    return (
        f'<form data-method="DELETE">{_id_field(note)}'
        '<button type="submit">Delete</button></form>'
    )


def _id_field(note: Annotation) -> str:
    """The annotation an edit or a deletion names."""
    return f'<input type="hidden" name="id" value="{escape(note.annotation_id)}">'


def _create_form() -> str:
    """The form that sends a ``POST``, which is the only one stating a timecode."""
    return (
        '<form class="new-note" data-method="POST">'
        '<label>Title <input name="title" required></label>'
        '<label>Timecode <input name="timecode" placeholder="1:30" required></label>'
        '<label>Body <input name="body"></label>'
        '<button type="submit">Add annotation</button></form>'
    )
