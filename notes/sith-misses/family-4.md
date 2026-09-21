# Family 4: sith checkpoint 5, refactoring commands

Runs: 1 = dev6-opus5 just-solve 20260830T0354, 2 = just-solve 20260915T1324, 3 = anti_slop 20260920T0212,
4 = min12 20260915T0053, 5 = min12 20260915T0719, 6 = min13 20260919T0435, 7 = min13 20260919T1433,
A = min11 20260908T0219, B = min11 20260908T0846. Registries exist in 4, 5, 6, 7, A, B only.

Paths: spec `~/.cache/scbench/problems/sith/checkpoint_5.md` (below `cp5.md`), tests
`~/.cache/scbench/problems/sith/tests/test_checkpoint_5.py` (`t5.py`), helpers `tests/helpers.py`,
reference `~/.cache/scbench/problems/sith/solutions/checkpoint_5/sith.py` (`ref.py`).
`bin/test-history` covers 13 sith runs; one (spectest-v10) never reached checkpoint 5, so counts are out of 12.

How the tests address a selection (shared by every extract test): `helpers.py:120-139` `locate_range` strips
`<<` and `>>` from the fixture and returns 1-based lines, 0-based columns, and an END POSITION THAT IS THE
OFFSET OF `>>`, i.e. one past the last selected character. When `>>` sits at the start of a line, the end is
`<next line>:0`. So `"def process(data):\n<<    total = 0\n ... total += item\n>>    return total\n"` becomes
`extract-function main.py 2 0 --until 5:0`: start before the indentation, end at column 0 of the line after
the selection.

What the extract tests compare: substrings of `changed_files["main.py"]` (or of the diff text). No test in
this family checks whole-file text, blank lines, or helper placement, except `test_extract_function_at_module_level`
which also checks `index("def setup_vars") < index("setup_vars(x)")`. Layout is not what fails anywhere here.

Four sentences, plus singles:

| # | Sentence | Tests | Class | pass/fail of 12 |
|---|----------|-------|-------|-----------------|
| S1 | cp5.md:67 "must span a complete expression" | 2 extract-variable | reading, and the hidden reading breaks the code | 0/12, 0/12 |
| S2 | cp5.md:82+85 `--until <line>:<col>` with "(full lines)" | 6 extract-function | reading | 3/9, 3/9, 4/8, 4/8, 4/8, 8/4 |
| S3 | cp5.md:87 parameter detection (run 4 only, on top of S2) | 2 extract-function in run 4 | process (agent bug) | inside S2's counts |
| S4 | cp5.md:27 rename scope, for `import X as Y` | alias rename | process (agent omission), unregistered everywhere | 3/9 |
| S5 | singles | 3 tests | process | 10/2, 11/1, 11/1 |

---

## S1. extract-variable: what "a complete expression" is

Tests: `test_extract_variable_inserts_assignment_and_replaces_expression`, `test_extract_variable_diff_output_is_unified_diff`. Fail in all 7 (and A, B).

### 1. Spec
cp5.md:64 `Extract the expression from `<line>:<col>` to `--until <line>:<col>` into a new variable.`
cp5.md:67 `- The selection must span a complete expression. If the selection cuts across an expression boundary (e.g., selects half a function call), exit 1 with `"selection is not a complete expression"`.`

### 2. Test and reference
t5.py:221-235 and 703-719. Fixture: `"def lerp(a, b, t):\n    return a + <<b - a>> * t\n"`, name `delta`,
argv `2 15 --until 2:20`. Asserts `"delta = b - a" in updated` and `"return a + delta * t" in updated`
(diff variant: `"+    delta = b - a"` and `"+    return a + delta * t"`).

`a + b - a * t` parses as `(a + b) - (a * t)`. Checked with `ast`: the BinOp spans are (0,13), (0,5), (8,13);
no node covers `b - a` (columns 4-9 of the expression). The expected output `delta = b - a; return a + delta * t`
computes `a + (b - a) * t`, a different value (a=1, b=3, t=0.5: 3.5 before, 2.0 after).

Reference, ref.py:4324-4331: slices the selected text and accepts it when it parses on its own:
```
selected_text = source[selection_start:selection_end]
try:
    ast.parse(selected_text, mode="eval")
except SyntaxError:
    print("selection is not a complete expression", ...)
```
It never checks that the text is one node of the enclosing tree. I ran it on the fixture; it prints
`"def lerp(a, b, t):\n    delta = b - a\n    return a + delta * t\n"`.

The sibling test `test_extract_variable_partial_expression_has_explicit_error_message` (t5.py:447-457) selects
`a +` in `return a + b` and wants exit 1; `a +` fails to parse, so the reference passes both.

### 3. What the runs printed
All seven: exit 1, stdout empty, stderr `sith: selection is not a complete expression` (run 2: `error: selection is
not a complete expression`). A and B the same. Every agent matches the selection against AST nodes. No run passes.

### 4. History
Both tests: 0 pass, 12 fail, 1 not reached. Includes sonnet-4.6, fable-5, fable-5-1.

### 5. Registry
Unregistered in all six registries: no entry asks whether "complete expression" means "text that parses alone"
or "one node of the tree". Closest entries, all quoting cp5.md:67 for other questions:
run 4 T98 "Which node wins when several expressions share the selected span"; run 6 T85 "Which node a selection
that several nodes share belongs to"; run 7 T82 "A selection that includes the brackets around an expression";
run A T93 "Whether a selection may include the parentheses around an expression". The end-column entries
(run 4 T90, run 5 T82, run 6 T73, run A T74, run B T83, quoted under S2) all chose exclusive, which matches
`2:15`-`2:20`. Every run's implicit choice (node match) misses the test's reading.

### 6. Classification
Reading, in the narrow sense that test and agent read "complete expression" differently (parses alone vs is a
node). But the hidden reading contradicts the spec's own first line (cp5.md:4 "transform code safely") since
the expected output changes what `lerp` returns. I read this as a fixture bug: the author likely meant
`a + (b - a) * t`. That is a guess about intent; the precedence fact is checked. Upstream issue candidate
(not in notes/upstream-prs.md as of this check).

### 7. Replacement sentence (cp5.md, line 67)
Only if the goal is to match the hidden test as it stands:
- "The selection is a complete expression when its text, taken alone, parses as a Python expression; otherwise exit 1 with `"selection is not a complete expression"`."
Over-correction to avoid: anything that says precedence or the enclosing tree is ignored. That invites agents to
drop the `a +` rejection or to stop parenthesising. Better fix is upstream: change the fixture to
`return a + (<<b - a>>) * t`, which every node-matching run would pass with the spec unchanged (guess, not run).

---

## S2. extract-function: how `--until <line>:<col>` addresses whole lines

Tests (6): `..._creates_helper_and_rewrites_callsite`, `..._diff_output_is_unified_diff` (fail 1-6),
`..._at_module_level`, `..._multiple_returns_preserve_source_order`, `..._multiple_returns_uses_tuple_unpacking`
(fail 1,2,3,5,6), `..._preserves_param_source_order` (fails 2,3,5).

### 1. Spec
cp5.md:79 `... extract-function <file> <line> <col> --until <line>:<col> --name <name> [--diff] [--project <dir>]`
cp5.md:82 `Extract the code from `<line>:<col>` to `--until <line>:<col>` into a new function.`
cp5.md:85 `- The selection must span one or more complete statements (full lines). If it spans a partial statement, exit 1.`
The spec never says whether `--until` is the last selected position or one past it, and never says that a
whole-line selection ends at `<next line>:0`. The only other use of "until" is the `errors` table
(cp5.md:109-110 "`until_line` 1-based end line", "`until_column` 0-based end column"), also silent on inclusive/exclusive.

### 2. Tests and reference
All six fixtures put `>>` at the start of the line after the selection, so argv is `2 0 --until N:0` where
line N is the first line NOT selected:
- t5.py:238-259 `"def process(data):\n<<    total = 0\n    for item in data:\n        total += item\n>>    return total\n"` -> `2 0 --until 5:0`; asserts `"def sum_values(data):" in updated`, `"total = sum_values(data)" in updated`. Diff variant t5.py:723-746 asserts `"+def sum_values(data):"`, `"+    total = sum_values(data)"`.
- t5.py:382-402 `"def process(a, b):\n<<    x = a + 1\n    y = b + 1\n>>    return x * y\n"` -> `2 0 --until 4:0`; asserts `"def compute_vals(a, b):"`, `"return x, y"`, `"x, y = compute_vals(a, b)"`.
- t5.py:902-921 same with `z`, `y`: `"return z, y"`, `"z, y = compute_vals(a, b)"`.
- t5.py:764-781 `"x = 10\n<<y = x + 1\nz = y * 2\n>>print(y, z)\n"` -> `2 0 --until 4:0`; asserts `"def setup_vars(x):"`, `"return y, z"`, `"y, z = setup_vars(x)"`, def before call.
- t5.py:602-619 `"def compute(z_var, a_var):\n<<    result = z_var + a_var\n>>    return result\n"` -> `2 0 --until 3:0`; asserts `"def add_values(z_var, a_var):"`.

Reference: ref.py:4462-4463 turns both positions into character offsets (half-open). ref.py:4479-4482 accepts a
start before the first statement if only whitespace lies between; ref.py:4490-4493 accepts an end after the last
statement if only whitespace lies between (`source[last_end:selection_end].strip() != ""`), and rejects when the
end cuts into the next statement. So `5:0` is "up to, not including, line 5". I ran it: `--until 5:0` gives
`def sum_values(data):\n    total = 0\n ...\n    return total\n\ndef process(data):\n    total = sum_values(data)\n    return total\n`.

### 3. What the runs printed (three behaviours for `--until N:0`)
(a) Line N counted as selected: runs 1 and 6. The `return` is swallowed, nothing is "used after", no return value.
 - Run 6 (pytest): `'def sum_values(data):\n    total = 0\n    for item in data:\n        total += item\n    return total\n\ndef process(data):\n    sum_values(data)\n'`; module level: `'x = 10\ndef setup_vars(x):\n    y = x + 1\n    z = y * 2\n    print(y, z)\n\nsetup_vars(x)\n'`; multi-return: `'def compute_vals(a, b):\n    x = a + 1\n    y = b + 1\n    return x * y\n\ndef process(a, b):\n    compute_vals(a, b)\n'`.
   Code: `snapshot/sithlib/extract.py:53` `selection = Selection.of(tree, buffer, line, until[0])`; columns are dropped, the until LINE is inclusive (its registry entry T88, below).
 - Run 1: same but `return sum_values(data)` and two blank lines. Code `snapshot/sith.py:5334-5368`: `if last_end == until_line and until_col:` treats column 0 as "no column given", so line N is whole. It has an `until[1] == 0` fallback to line N-1 (sith.py:5598) but only when the first attempt fails, and it does not fail.
 - Both pass `preserves_param_source_order` because swallowing `return result` still yields `def add_values(z_var, a_var):`.
(b) Exit 1, line N seen as half-selected: runs 2, 3, 5 (and B). stderr: run 2 `error: selection does not span whole statements`; run 3 `sith: selection is not a complete run of statements`; run 5 `sith: selection is not a complete set of statements`; run B `sith: selection is not a complete statement`. All six tests fail, including param order.
(c) `N:0` read as end of line N-1: runs 4, 7 (and A; fable-5-1 also passes all six, its code not read).
 - Run 7 passes all six. Code `snapshot/sithlib/selections.py:39-41`: `if until_column == 0 and until_line > line: until_line -= 1; until_column = len(lines[until_line - 1])`. Output on the fixture (I ran the snapshot): identical to the reference's.
 - Run A: `snapshot/sith.py:3735` `if run is None and until_col == 0 and until_line > line:` fallback; passes all six.
 - Run 4: compares exact (line, col) pairs half-open (`snapshot/sith.py:4264-4278`), so `5:0` works; passes the three return-value tests; fails the two `sum_values` tests for a different reason, see S3.

Run 6 vs run 7, the one differing choice: run 6 ignores the columns of an extract-function selection and takes
both line numbers as inclusive; run 7 keeps columns and rewrites `N:0` to the end of line N-1. Check: I ran
run 6's snapshot with `--until 4:21` (end of the last selected line) and it printed exactly the expected text
(`total = sum_values(data)` and all). Its only miss is the addressing, not parameters, returns or layout.
(Side observation, not chased: run 5's snapshot with `2 0 --until 4:21` prints a mis-indented body, so run 5 may
have a second problem with a start column left of the indentation. Guess from one invocation.)

### 4. History
creates_helper 3/9, diff 3/9 (pass: fable-5-1, A, 7). module_level and both multiple_returns 4/8 (pass: fable-5-1, A, 4, 7).
param order 8/4 (fail: 2, 3, 5, B). One not reached in each.

### 5. Registry
Only run 7 registered the question the tests turn on (whole lines written as `<next line>:0`), and its Choice
matches. Runs 4, 5, 6, A, B registered the neighbouring question (is the end column inclusive or exclusive),
all chose exclusive, which is the tests' reading for columns, yet 5, 6, B still miss because exclusive was never
carried over to the LINE. Run 6 T88 and run 5 T84 are the entries whose Choice produces the miss. Run A passes
through an unregistered fallback in code.

**Run 7, T87 (Choice matches the tests):**

~~~~text
## T87 — Whole-line selections written as `--until <next line>:0`

### Spec Text
> The selection must span one or more complete statements (full lines).

### Alternatives
1. A selection ending at column 0 of the following line is the editor's way of writing "up to the end of the previous line", and is read that way.
2. It is taken literally, so the statement on the following line is half-selected and the command exits 1.

### Choice
Alternative 1. Editors produce that range whenever whole lines are selected,
and the parenthesis in the spec - "(full lines)" - points at exactly that
gesture.

### Risk: 30
A literal reading would exit 1 where this tool extracts.
~~~~

**Run 6, T73 (exclusive column: matches, but applied to extract-variable only):**

~~~~text
## T73. Whether `--until` names the last character or the one past it

### Spec Text
> "`python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name>`"
> "Extract the expression from `<line>:<col>` to `--until <line>:<col>` into a new variable."

### Alternatives
1. `--until` is exclusive: it is the position just past the last character of the
   selection, which is what `end_col_offset` holds in the AST and what the `errors`
   command reports as `until_column`.
2. `--until` is inclusive: it is the position of the last character itself.

### Choice
(1). A selection is compared against a node's own span, and the span the parser records
ends one past the last character; the same command set reports error ranges that way in
`errors`. Accepting both readings was rejected on purpose: `f(x` widened by one becomes
the complete `f(x)`, which would swallow the "selects half a function call" refusal the
spec asks for.

### Risk: 20
Author most likely prefers: (1), since the natural implementation compares the given
positions with `node.col_offset` / `node.end_col_offset` directly.
~~~~

**Run 6, T88 (Choice misses: columns ignored, so the until line becomes inclusive; note its own text names "0 of the next line" and the code still selects that line):**

~~~~text
## T88. Whether the columns of an `extract-function` selection are checked

### Spec Text
> "Extract the code from `<line>:<col>` to `--until <line>:<col>` into a new function."
> "The selection must span one or more complete statements (full lines)."

### Alternatives
1. Only the lines matter; the columns are ignored, since the selection is defined in terms
   of full lines.
2. The columns must also land exactly on the start and end of the statement run.

### Choice
(1). "(full lines)" says what the unit is. An editor selecting whole lines puts the end
column at 0 of the next line or at the end of the last one, and neither is the statement's
own end column, so checking columns would refuse the ordinary case.

### Risk: 20
Author most likely prefers: (1).
~~~~

**Run 6, T87 (neighbour, not the cause):**

~~~~text
## T87. Blank lines and comments at the edge of a statement selection

### Spec Text
> "The selection must span one or more complete statements (full lines). If it spans a
> partial statement, exit 1."

### Alternatives
1. Blank lines and comment lines at either end of the selection are ignored, and the run
   of statements inside them is extracted.
2. They make the selection fail to line up with any run of statements, so it is refused.

### Choice
(1). A comment or a blank line is not a statement, so a selection wrapping one is not
spanning a partial statement -- the thing the spec refuses. Narrowing keeps the common
editor gesture of selecting a block with its trailing blank line working.

### Risk: 25
Author most likely prefers: (1), though a strict line-for-line comparison against the
statement run would answer (2).
~~~~

**Run 5, T82 (exclusive column: matches):**

~~~~text
## T82. Whether `--until <line>:<col>` points at the last character or one past it

### Spec Text
> Extract the expression from `<line>:<col>` to `--until <line>:<col>` into a new variable.

### Alternatives
1. Exclusive: `--until` names the position *after* the selection, so `2 * 3` in `x = 1 + 2 * 3` is `1:8` to `1:13`. This is how editors report a selection end and how `ast` reports `end_col_offset`.
2. Inclusive: `--until` names the last selected character, so the same selection is `1:8` to `1:12`.

### Choice
Alternative 1. Every other column in this tool is a cursor position rather than a character index, and
an implementation that matches a selection against `ast` node positions gets the exclusive convention
for free — `node.end_col_offset` *is* the exclusive end. The sibling `errors` command uses
`until_column` for the exclusive end of an error span in the same way. Trailing whitespace inside the
selection is ignored, so a selection that runs to the end of a line still matches.

The two readings cannot be reconciled by accepting both: `b + ` under the inclusive reading is the
valid expression `b + c`, so tolerating inclusive ends would silently accept selections that cut across
an expression boundary — exactly what the spec requires be rejected.

### Risk: 30
The author most likely prefers: exclusive (this choice). If they chose inclusive, every positive
extraction fixture is off by one and fails.
~~~~

**Run 5, T84 (Choice misses: "the end must reach the last non-blank column of the last line", and `5:0` does not):**

~~~~text
## T84. What `extract-function` checks before calling a selection "complete statements"

### Spec Text
> The selection must span one or more complete statements (full lines). If it spans a partial statement, exit 1.

### Alternatives
1. Line-oriented: the text before the start column on the first line must be blank, the end must reach the last non-blank column of the last line, and the statements of one suite must tile the line range exactly with nothing hanging over either edge.
2. Line numbers only: any selection whose first and last lines coincide with statement boundaries is accepted, ignoring the columns entirely.
3. Exact offsets: the selection must start and end exactly on the statement's own span.

### Choice
Alternative 1. The parenthetical "(full lines)" says the unit is a line, not an offset, which rules out
(3); but the rule is introduced as a *check* ("if it spans a partial statement, exit 1"), so the columns
cannot be ignored altogether as in (2) — `a = <sel>1 + 2</sel>` has to fail, and it fails on the column.
The end-column test allows one character of slack so that a selection ending on the last character of
the line is accepted as readily as one ending past it.

### Risk: 30
The author most likely prefers: a line-oriented check with a start-column test (this choice); the
residual risk is that they ignore columns entirely, so a fixture selecting a sub-expression on a single
full line expects a successful extraction where this implementation exits 1.
~~~~

**Run 4, T90 (exclusive, matches; its exact-offset comparison handles `N:0` without a special case):**

~~~~text
## T90. Is the `--until <line>:<col>` column exclusive or inclusive?

### Spec Text
> `python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name>`
> Extract the expression from `<line>:<col>` to `--until <line>:<col>` into a new variable.

### Alternatives
1. The end column is exclusive — a half-open `[start, until)` span, matching Python's own
   `end_col_offset` and this tool's existing `until_column` field for `errors`.
2. The end column is inclusive — `until` names the last character of the selection.

### Choice
Interpretation 1 (exclusive). The `errors` subcommand in this very spec defines
`until_column` as the end column of a `SyntaxError`, and CPython's `end_col_offset` /
`end_offset` are both one past the last character; a spec that reuses the word `until` for both
is almost certainly reusing the convention. Selecting `a + b` out of `x = a + b` is then
`4` to `9`, exactly the node's `(col_offset, end_col_offset)`.

No inclusive fallback is attempted: retrying with `until + 1` would silently accept
`foo(a` (start of a call through its first argument) as the complete call `foo(a)`, which is the
one case the spec explicitly wants to reject.

### Risk: 20
Author most likely prefers: the same half-open convention.
~~~~

**Run A, T74 (exclusive, matches; the `N:0` fallback at sith.py:3735 is not registered):**

~~~~text
## T74 — Whether `--until <line>:<col>` is an inclusive or an exclusive end column

### Spec Text
> `python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name>`

> Extract the expression from `<line>:<col>` to `--until <line>:<col>` into a new variable.

> The selection must span a complete expression. If the selection cuts across an expression boundary (e.g., selects half a function call), exit 1 with `"selection is not a complete expression"`.

### Alternatives
1. Exclusive: the until column is one past the last selected character, i.e. exactly
   `ast` node `end_col_offset`. `a + b` in `y = a + b` is `1:4` to `1:9`.
2. Inclusive: the until column is the last selected character, `1:4` to `1:8`.
3. Accept either, preferring an exact `end_col_offset` match and falling back to `+1`.

### Choice
Alternative 1. Every other column in this tool is a 0-based offset and `references`,
`goto` and `names` all report a name's *start* offset, so a half-open `[start, until)`
span is the only convention that composes with them; it is also literally the pair
`(col_offset, end_col_offset)` that `ast` hands an implementation, so it needs no
arithmetic. Alternative 3 was implemented and then abandoned: accepting `until+1` makes
`y = <compute(1> ) + 2` — half a function call — match the `compute(1)` Call node, which
directly contradicts the spec's own worked counter-example.

### Risk: 35
If the author's implementation is inclusive, every selection fixture in the hidden tests
is off by one and no `extract-*` test would pass; the counter-example in the spec is the
main evidence against that.
~~~~

**Run B, T83 (exclusive, but reads full lines as "`col 0` to `len(line)`", so `N:0` exits 1: misses):**

~~~~text
## T83. Is `--until <line>:<col>` inclusive or exclusive?

### Spec Text
> Extract the expression from `<line>:<col>` to `--until <line>:<col>` into a new variable.
> | `until_column` | int | 0-based end column. |

### Alternatives
1. Exclusive: the selection is `[start, until)`, matching `end_col_offset` in the AST and the `until_column` the `errors` command reports.
2. Inclusive: `until` names the last character of the selection.
3. Accept either, preferring whichever finds a node.

### Choice
Alternative 1. The same phase gives `errors` an `until_line`/`until_column` pair that comes straight from the parser's exclusive end position, so the word "until" is already fixed to that meaning inside this spec; it also makes "full lines" for `extract-function` come out as `col 0` to `len(line)`, the two numbers an editor has to hand. (3) was rejected because it would silently accept selections such as `f(a` that the spec explicitly wants rejected.

### Risk: 25
If the author's fixtures were written with an inclusive end, every extraction offset is off by one and the selections here fail with "not a complete expression".
~~~~

Layout entries exist in every registry (run 4 T92 and T108, run 5 T85, run 6 T83, run 7 T83, run A T84, run B T86)
and none is implicated: the tests compare substrings only.

### 6. Classification
Reading. One sentence pair (cp5.md:82 + 85), three readings of `--until N:0`, and the spec picks none. The
hidden reading is the ordinary editor one and is consistent with the spec.

### 7. Replacement sentence (cp5.md; put it once, under `extract-variable` line 64 or as a Clarifications bullet, since both extract commands share it)
- "`<line>` is 1-based and `<col>` is 0-based. `--until` names the position just after the last selected character, so lines 2 to 4 selected whole are `2 0 --until 5:0`; line 5 is not part of that selection."
- Shorter, for cp5.md:85: "The selection must span one or more complete statements (full lines); a whole-line selection starts at column 0 of its first line and ends at column 0 of the line after its last."
Over-correction to avoid: do not say columns are ignored for extract-function (that is run 6's T88 and it is the
miss), and do not require the end to be `N:0`: `test_extract_function_partial_statement_selection_exits_1` uses
`3 8 --until 4:16`, and the reference also accepts an end at the last statement's own end column.

---

## S3. Run 4 only: `def sum_values(total, data)`

Tests: `creates_helper` and `extract_function_diff` in run 4 (they fail in 1-6; in run 4 for this reason, not S2).

1. Spec, cp5.md:87: `- **Parameter detection:** Variables read in the selected statements but defined outside the selection become function parameters, ordered by first appearance in the selected code.`
2. Test: as S2; wants `"def sum_values(data):"`. Reference ref.py:4523-4527 skips any name assigned inside the selection (`if node.id in assigned_names: continue`).
3. Run 4 printed `'def sum_values(total, data):\n    total = 0\n ...\n    return total\n\ndef process(data):\n    total = sum_values(total, data)\n    return total\n'`. `total` is first bound by `total = 0` inside the selection, so it is not "defined outside". Cause, `snapshot/sith.py:4379-4382`: `if load or ident in augmented:` fires on the plain store `total = 0` because `total` is also an aug-assign target later, and `_outside_variables` (4317-4327) lists every assignment of the enclosing function, including the ones inside the selection. The emitted call `sum_values(total, data)` reads an unbound local. Runs 7 and A print `def sum_values(data):`.
4. History: inside S2's 3/9.
5. Unregistered in run 4 (grep for "augment" and "+=" finds only T16, T28, T100, none about extract). Closest: run 4 T97 "Do functions, classes and imports become `extract-function` parameters?".
6. Process: agent bug against words the spec already has.

---

## S4. rename: the imported name in `from shapes import Circle as Shape`

Test: `test_rename_updates_alias_backed_references_without_touching_other_aliases`. Fails 3,4,5,6,7 (and A, B); passes 1, 2.

### 1. Spec
cp5.md:27 `**Rename scope:** All references found via the same logic as `references --scope project` are renamed.`
cp5.md:32 `- All import statements referencing the old name are updated.` (under Module renames, so strictly about modules).
checkpoint_4.md:59 `For project-scope search, return only occurrences that resolve to the same symbol identity as the cursor target (do not include same-spelling but unrelated symbols in other scopes).`
Nothing in either file mentions `as`. A checkpoint-5 agent sees only cp5.md and its own `references` code.

### 2. Test and reference
t5.py:842-869. `shapes.py`: `"class Circle:\n    pass\n"`. `main.py`: `"from shapes import Circle as Shape\nfrom shapes import Circle as Alternate\nitem = Shape()\nother = Alternate()\n"`. Rename `Circle` (cursor in shapes.py) to `Ring`. Asserts `changed_files["main.py"]` contains `from shapes import Ring as Shape`, `from shapes import Ring as Alternate`, `item = Shape()`, `other = Alternate()`.
Reference (I ran checkpoint_4 and checkpoint_5 solutions on the fixture): `references --scope project` lists main.py 1:19 and 2:19 (`is_definition: false`) plus shapes.py 1:6; `rename` rewrites both import lines and leaves the aliases.

### 3. What the runs printed
Pytest shows `KeyError: 'main.py'` in all of 3,4,5,6,7,A,B. I ran each snapshot on the fixture:
- 3,4,5,6,7,A,B: `{"changed_files":{"shapes.py":"class Ring:\n    pass\n"},"renames":{}}`, and their `references --scope project` returns shapes.py 1:6 only. `main.py` is left importing a name that no longer exists: the refactor breaks the program.
- With a plain `from shapes import Circle` + `Circle()` (my variant), runs 4, 6, 7 do list main.py 1:19 and 2:7. So only the `as` form is missed. Run 6's cause: `snapshot/sithlib/references.py:83-89` collects bindings with `binding.name == name`, and an aliased import binds `Shape`, so the `Circle` token is never a candidate. (Runs 3,4,5,7,A,B: same symptom; I did not read their code.)
- Run 1: `references` also returns shapes.py only, but `rename` rewrites both import lines (its rename is wider than its references). Run 2: `references` lists main.py 1:19 and 2:19 and rename follows.

### 4. History
3 pass (run 1, fable-5-1, run 2), 9 fail, 1 not reached.

### 5. Registry
Unregistered in all six. No entry asks whether the imported name in `import X as Y` is an occurrence of X.
Closest, all on checkpoint_4.md:59: run 4 T72 (quoted below because its Choice text claims the alias case and
the code does not deliver it), run 5 T61 "What identifies "the same symbol" across positions and files", run 6 T58
"Whether file-scope `references` filters by symbol identity", run 7 T52 "Which occurrences a file-scope `references`
search keeps", run A T57 "Whether file-scope `references` filters by symbol identity", run B T66 "Do attribute
occurrences (`obj.name`) count as references?" (its alternative 2 lists "import aliases" as bare-name occurrences).

**Run 4, T72 (Choice on paper matches the tests; the implementation misses the `as` form):**

~~~~text
## T72. What "the same symbol identity" means

### Spec Text
> For project-scope search, return only occurrences that resolve to the same symbol identity as
> the cursor target (do not include same-spelling but unrelated symbols in other scopes).

### Alternatives
1. Identity is the defining binding: two occurrences match when following each of them to a
   definition (through imports) lands on the same source location.
2. Identity is the fully-qualified dotted name.
3. Identity is nominal — anything spelled the same in a reachable scope.

### Choice
Interpretation 1. It is the only reading that distinguishes a local `x` in one function from a
local `x` in another (same qualified name is not available for locals, and same spelling is
explicitly excluded). Occurrences are matched by intersecting the `goto --follow-imports`
result sets, so an `import` alias, the imported name and the original `def` all share one
identity. The same rule is applied for `--scope file`, so file scope is simply project scope
restricted to one file.

### Risk: 30
Author most likely prefers: the same for project scope. For `--scope file` the spec only says
"search only within the target file", so an author whose file-scope path is a plain name scan
would also report unrelated same-spelling locals.
~~~~

### 6. Classification
Process: an omitted case, not a reading. No run chose to leave the import line alone; the token was never
considered, and the result is a broken import, which no reading of "rename ... all its references" defends.
The split "passes in the two no-registry runs" looks like coincidence of architecture (spelling-first candidate
filter) rather than an effect of the registry: run 3 has no registry and fails, and sonnet-4.6 and fable-5 fail too.
That last sentence is inference from the pass/fail table, not from reading those runs' code.
A spec sentence can still help because the miss is systematic (9 of 12).

### 7. Candidate sentence (cp5.md, after line 27)
- "A reference includes the imported name in an aliased import: renaming `Circle` rewrites `from shapes import Circle as Shape` to `from shapes import Ring as Shape`, and `Shape` and its uses stay as written."
Over-correction to avoid: wording like "aliases are references" would push agents to rename `Shape` itself, which the test forbids (`item = Shape()` must survive).

---

## S5. Singles

- `test_extract_function_partial_statement_selection_exits_1` (run 4 only; history 10 pass / 2 fail, the other is sonnet-4.6). Fixture `"def process(data):\n    for item in data:\n        <<value = item\n    return value>>\n"` -> `3 8 --until 4:16`, wants exit 1 (cp5.md:85 "If it spans a partial statement, exit 1"). Run 4 exits 0 and extracts only `value = item` (I ran it: `def extract_me(item): ... value = extract_me(item)`): `_pick_statements` (snapshot/sith.py:4264-4278) walks outermost-first, rejects the function body (the `for` is touched but not inside), then accepts the `for` body where `value = item` is inside, and never checks that the selection also reaches `return value` outside that block. Process, agent bug; unregistered in run 4.
- `test_extract_variable_keyword_name_exits_1` (`--name for`) and `test_rename_keyword_new_name_exits_1` (`--new-name class`), run 3 only; history 11 pass / 1 fail each. cp5.md:35 "`--new-name` must be a valid Python identifier. If not, exit 1." and cp5.md:70. Run 3 validates with `name.isidentifier()` alone (`snapshot/sithlib/selections.py:29`), which is True for keywords; it exits 0. Run 3 has no registry. Registry runs that named it all chose to reject keywords: run 4 T94, run 7 T72, run A T73, run B T88 (runs 5 and 6 have no such title and still pass). Process (a known `isidentifier` trap, one run of 12). If a word is wanted: "a valid Python identifier that is not a keyword".
