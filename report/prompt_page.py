#!/usr/bin/env python3
"""Build report/<name>-prompt.html: a prompt's Jinja source rendered as a page.

    python3 report/prompt_page.py min12-ABDJKMN min13-ABDJKMNT

Reads configs/prompts/<name>.jinja. Every `#` heading in the source is a section; the first is
the title and the rest are subsections. Template tags stay in place, `{% %}` as teal marks and
the `{{ spec }}` slot as an amber block, so the page shows what the agent is sent without a
spec filled in. Bullets nest by indentation; a line's `backticks` become code; blank lines end
a paragraph block. The stylesheet is prompt-page.template.html, which min12-prompt.html was
first written with by hand.
"""
import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LABELS = {"min12-ABDJKMN": "spectest prompt", "min13-ABDJKMNT": "spectest+antislop prompt"}
TAG = re.compile(r"\{%-?\s*(.*?)\s*-?%\}")
SLOT = re.compile(r"\{\{\s*(.*?)\s*\}\}")


def inline(text):
    """A line of prose as HTML: escaped, `code` spans, template tags as marks."""
    out, pos = [], 0
    for m in re.finditer(r"\{%-?\s*.*?\s*-?%\}|\{\{\s*.*?\s*\}\}|`[^`]+`", text):
        out.append(html.escape(text[pos:m.start()]))
        piece = m.group(0)
        if piece.startswith("`"):
            out.append(f"<code>{html.escape(piece[1:-1])}</code>")
        elif piece.startswith("{{"):
            out.append(f'<code class="tpl slot">{html.escape(SLOT.match(piece).group(1))}</code>')
        else:
            out.append(f'<code class="tpl">{html.escape(TAG.match(piece).group(1))}</code>')
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def bullets(lines):
    """Nested <ul> from '- ' lines indented by two spaces per level."""
    out, depth = [], -1
    for line in lines:
        level = (len(line) - len(line.lstrip())) // 2
        text = inline(line.strip()[2:])
        while depth < level:
            out.append("<ul>")
            depth += 1
        while depth > level:
            out.append("</li></ul>")
            depth -= 1
        if out and out[-1] not in ("<ul>",):
            out.append("</li>")
        out.append(f"<li>{text}")
    out.append("</li>" + "</ul>" * (depth + 1))
    return "".join(out)


def render_body(source):
    blocks, paragraph, items, seen_title = [], [], [], False

    def flush():
        nonlocal paragraph, items
        if items:
            blocks.append(bullets(items))
            items = []
        if paragraph:
            blocks.append('<div class="p">' + "".join(f"<p>{inline(p)}</p>" for p in paragraph) + "</div>")
            paragraph = []

    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped.startswith("# "):
            flush()
            blocks.append(f"<h{2 if seen_title else 1}>{html.escape(stripped[2:])}</h{2 if seen_title else 1}>")
            seen_title = True
        elif TAG.fullmatch(stripped) or SLOT.fullmatch(stripped):
            flush()
            kind = "tpl slot" if stripped.startswith("{{") else "tpl"
            name = (SLOT if stripped.startswith("{{") else TAG).fullmatch(stripped).group(1)
            blocks.append(f'<div class="tplline"><code class="{kind}">{html.escape(name)}</code></div>')
        elif stripped.startswith("- "):
            if paragraph:
                flush()
            items.append(line)
        else:
            if items:
                flush()
            paragraph.append(stripped)
    flush()
    return "\n".join(blocks)


def prose_words(source):
    """Words in the source with the template tags and the bullet dashes removed."""
    return sum(1 for word in SLOT.sub(" ", TAG.sub(" ", source)).split() if word != "-")


def build(name):
    source = (ROOT / "configs" / "prompts" / f"{name}.jinja").read_text()
    template = (HERE / "prompt-page.template.html").read_text()
    body = render_body(source)
    return template.replace("{{title}}", html.escape(f"Spectest prompt: {name}")).replace(
        "{{meta}}", f'<b>configs/prompts/{name}.jinja</b><span>{prose_words(source)} words of prose</span>'
                    f"<span>{LABELS.get(name, 'prompt')}</span>").replace("{{body}}", body)


if __name__ == "__main__":
    for name in sys.argv[1:]:
        short = name.split("-")[0]
        (HERE / f"{short}-prompt.html").write_text(build(name))
        print(f"wrote report/{short}-prompt.html")
