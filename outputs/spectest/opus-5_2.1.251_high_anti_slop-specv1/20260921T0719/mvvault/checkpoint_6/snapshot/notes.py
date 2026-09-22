"""The annotations section of an entry detail page.

The section lists what the entry carries, in catalog order and with every
timecode as the raw seconds it is stored as, and carries the form and the
buttons that ask the entry route to create, update and delete them.  Playback
follows the page: a ``timecode`` query seeks the player to that second, and
every annotation links to the second it marks.
"""

from html import escape
from urllib.parse import urlencode

import annotations
import viewer
from annotations import Annotation
from catalogs import Entry

STYLE = """
section.annotations ol { list-style: none; padding-left: 0; }
li.annotation { border-left: 3px solid #2a78d6; margin: 0.5rem 0; padding-left: 0.5rem; }
li.annotation a.seek { font-variant-numeric: tabular-nums; margin-right: 0.5rem; }
li.annotation p.body { color: #52514e; margin: 0.25rem 0; }
form.annotation label { display: block; margin: 0.25rem 0; }
"""

#: Asks the entry route for a change, and follows it to wherever it answers.
#: A refusal is shown as the page it was refused with, so the visitor reads
#: what was wrong with the annotation rather than watching nothing happen.
FORMS = """
const show = markup => {
  document.open();
  document.write(markup);
  document.close();
};

const send = (method, payload) =>
  fetch(location.pathname, {
    method: method,
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  }).then(answer =>
    answer.ok ? location.assign(answer.url) : answer.text().then(show)
  );

document.querySelectorAll('form.annotation').forEach(form => {
  form.addEventListener('submit', event => {
    event.preventDefault();
    send(form.dataset.method, Object.fromEntries(new FormData(form)));
  });
});

document.querySelectorAll('button.delete').forEach(button => {
  button.addEventListener('click', () => send('DELETE', {id: button.value}));
});
"""

#: Starts playback at the second the page was opened on, when it was opened
#: on one and the vault holds media to play.
SEEK = f"""
const moment = new URLSearchParams(location.search).get('{viewer.TIMECODE_QUERY}');
const player = document.querySelector('video.media');
if (moment !== null && player) {{
  player.currentTime = Number(moment);
}}
"""

#: The form a new annotation is written in, below the ones already stored.
CREATE_FORM = (
    "<form class='annotation' data-method='POST'>"
    "<label>Title <input name='title' required></label>"
    "<label>Timecode <input name='timecode' placeholder='1:30' required></label>"
    "<label>Body <input name='body'></label>"
    "<button type='submit'>Annotate</button></form>"
)


def section(entry: Entry) -> str:
    """The annotations of an entry, with the forms that change them."""
    items = "".join(_item(annotation) for annotation in annotations.of(entry))
    return (
        "<section class='annotations'><h3>Annotations</h3>"
        f"<ol>{items}</ol>{CREATE_FORM}<script>{FORMS}{SEEK}</script></section>"
    )


def _item(annotation: Annotation) -> str:
    """One annotation: the second it marks, what it says and how to change it."""
    identifier, timecode = annotation["id"], annotation["timecode"]
    title, body = annotation["title"], annotation["body"] or ""
    seek = urlencode({viewer.TIMECODE_QUERY: timecode})
    return (
        f"<li class='annotation' id='{escape(identifier)}'>"
        f"<a class='seek' href='?{seek}'>{timecode}</a>"
        f"<span class='title'>{escape(title)}</span>"
        f"<p class='body'>{escape(body)}</p>"
        f"{_edit_form(identifier, title, body)}"
        f"<button class='delete' value='{escape(identifier)}'>Delete</button></li>"
    )


def _edit_form(identifier: str, title: str, body: str) -> str:
    """The form one stored annotation is rewritten in, folded away until used."""
    return (
        "<details><summary>Edit</summary>"
        "<form class='annotation' data-method='PATCH'>"
        f"<input type='hidden' name='id' value='{escape(identifier)}'>"
        f"<label>Title <input name='title' value='{escape(title)}'></label>"
        f"<label>Body <input name='body' value='{escape(body)}'></label>"
        "<button type='submit'>Save</button></form></details>"
    )
