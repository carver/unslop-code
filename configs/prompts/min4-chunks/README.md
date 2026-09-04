# Prompt chunks of min4

`spectest-min4-ambiguities.jinja` cut into one rule per file. `bin/build-prompt BEG` writes
`configs/prompts/min4-BEG.jinja`: HEAD, then the chosen chunks in letter order separated
by blank lines, then TAIL. Letters are canonical, so `GEB` and `BEG` build the same file.
`bin/build-prompt --list` prints this index from the files.

Chunks that read as a sequence: G says "then, add a numbered entry" and expects F before
it; H and I refer to "the entry" and "a choice", so they expect G. Nothing enforces that;
a set that skips a prerequisite is a legitimate experiment, just read the built file.

The existing rungs as chunk sets: min2 = ADEJK, min2b = ABCJK, min3 = ABCDEJK,
min4 = ABCDEFGHIJK (identical to the rung apart from blank lines between chunks that the
rung ran together). min0 and min1 use different sentences and are not chunk sets.
