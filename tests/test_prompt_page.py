"""report/prompt_page.py: a prompt's Jinja source rendered as the min12 page was, for any prompt."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report"))
import prompt_page as pp  # noqa: E402

SOURCE = """# Task Directions

Fully implement the spec. Use the approach:
- Environment setup
- Implement

Specifically:

# Environment

{% if not is_continuation -%}
Use a virtual environment with a `requirements.txt`.
{%- else -%}
Keep the same environment.
{%- endif %}

Touch an IN_PROGRESS file.
Why? It's <easy> & "quick".

# Implement

- Follow best coding practices:
  - Keep your code clean
- No god functions.

# Spec

{{ spec.strip() }}
"""


def test_blocks_keep_the_sources_shape():
    html = pp.render_body(SOURCE)
    assert "<h1>Task Directions</h1>" in html
    assert "<h2>Environment</h2>" in html and "<h2>Spec</h2>" in html
    assert '<ul><li>Environment setup</li><li>Implement</li></ul>' in html
    assert '<div class="tplline"><code class="tpl">if not is_continuation</code></div>' in html
    assert '<div class="tplline"><code class="tpl slot">spec.strip()</code></div>' in html
    assert ('<div class="p"><p>Touch an IN_PROGRESS file.</p>'
            '<p>Why? It&#x27;s &lt;easy&gt; &amp; &quot;quick&quot;.</p></div>') in html
    assert "<code>requirements.txt</code>" in html


def test_a_nested_list_nests():
    html = pp.render_body(SOURCE)
    assert ("<ul><li>Follow best coding practices:<ul><li>Keep your code clean</li></ul></li>"
            "<li>No god functions.</li></ul>") in html


def test_the_min12_page_is_reproduced_from_its_source():
    built = pp.build("min12-ABDJKMN")
    # the page as it was written by hand (commit 258e4e6), before this script existed; it said 425 words
    # where no count of the source gives that, so the page takes the tool's count. The copy is a fixture,
    # not `git show`, so the test runs in a shallow clone and in a release archive without .git.
    kept = (ROOT / "tests" / "fixtures" / "min12-prompt-258e4e6.html").read_text()
    strip = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    assert strip(built) == strip(kept).replace("425 words", "423 words")


def test_word_count_is_of_the_prose_not_the_template_tags():
    assert pp.prose_words("Fully implement.\n{% if x -%}\n- Two words\n{%- endif %}\n{{ spec.strip() }}\n") == 4
