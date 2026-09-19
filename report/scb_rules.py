"""Which ast-grep rules flag a tree's lines, on the scale of scb-check's ast%.

ast% is flagged lines over LOC, and scb-check's LOC leaves out blank lines, comments and
docstrings. `rule_lines` puts each hit (scb_hits) on the same footing: the code lines under its
spans, a line counted once per rule. `breakdown` sets the counts beside the checker's own
(scb_split), so a table of them can be read against ast%: the union of all rules comes within a
few percent of scb-check's flagged count, and the denominator is its LOC.

    {"loc", "scb_ast_lines", "union", "rules": {rule: flagged code lines}}
"""
import ast
import io
import tokenize

import scb_split

LAYOUT_TOKENS = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                 tokenize.ENDMARKER}
DOCUMENTED = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def docstring_lines(module):
    lines = set()
    for node in ast.walk(module):
        if isinstance(node, DOCUMENTED) and ast.get_docstring(node, clean=False) is not None:
            lines.update(range(node.body[0].lineno, node.body[0].end_lineno + 1))
    return lines


def code_lines(text):
    """Line numbers that hold code: no blanks, comments or docstrings. Text Python cannot parse
    gets the rough answer, every line that is not blank or a comment."""
    try:
        module = ast.parse(text)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, tokenize.TokenError):
        return {n for n, line in enumerate(text.splitlines(), 1) if line.strip() and not line.strip().startswith("#")}
    lines = set()
    for token in tokens:
        if token.type not in LAYOUT_TOKENS:
            lines.update(range(token.start[0], token.end[0] + 1))
    return lines - docstring_lines(module)


def rule_lines(tree, hits, part):
    """{rule: {(file, line)}} for the ast-grep hits in `part` ("impl", "test" or "all") of `tree`."""
    code = {str(f): code_lines((tree / f).read_text(errors="replace")) for f in scb_split.python_files(tree)
            if part == "all" or scb_split.part_of(f) == part}
    found = {}
    for hit in (h for h in hits if h["kind"] == "ast"):
        lines = found.setdefault(hit["rule"], set())
        for span in hit["spans"]:
            flagged = code.get(span["file"], set()).intersection(range(span["start"], span["end"] + 1))
            lines.update((span["file"], n) for n in flagged)
    return found


def breakdown(tree, part, hits, counts):
    """`hits` from scb_hits.load(tree), `counts` from scb_split.split_reports(tree)."""
    lines = rule_lines(tree, hits, part)
    return {"loc": counts[part]["total_loc"], "scb_ast_lines": counts[part]["ast_grep_flagged_loc"],
            "union": len(set().union(*lines.values())), "rules": {rule: len(found) for rule, found in lines.items()}}


def per_thousand(lines, loc):
    return 1000 * lines / loc if loc else None


def fmt(value):
    return "-" if value is None else format(value, ".1f")


def table(columns, floor):
    """Markdown, one column per breakdown (each with a "name"), one row per rule. Rules are sorted
    by how far the columns disagree; those under `floor` in every column share one summed row."""
    def row(label, values):
        return f"| {label} | " + " | ".join(values) + " |"

    rates = {rule: [per_thousand(c["rules"].get(rule, 0), c["loc"]) or 0 for c in columns]
             for rule in {rule for c in columns for rule in c["rules"]}}
    shown = sorted((r for r in rates if max(rates[r]) >= floor), key=lambda r: (min(rates[r]) - max(rates[r]), r))
    hidden = [r for r in rates if r not in shown]
    lines = [row("flagged lines per 1000 LOC", [c["name"] for c in columns]), "|---|" + "---|" * len(columns),
             row("LOC", [str(c["loc"]) for c in columns]),
             row("scb-check ast", [fmt(per_thousand(c["scb_ast_lines"], c["loc"])) for c in columns]),
             row("all rules, each line once", [fmt(per_thousand(c["union"], c["loc"])) for c in columns])]
    lines += [row(rule, [fmt(rate) for rate in rates[rule]]) for rule in shown]
    if hidden:
        lines.append(row(f"{len(hidden)} rules under {fmt(floor)} everywhere, summed",
                         [fmt(sum(rates[r][i] for r in hidden)) for i in range(len(columns))]))
    return "\n".join(lines)
