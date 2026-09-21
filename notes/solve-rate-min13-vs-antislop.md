# Does spectest+antislop solve more than anti-slop on the patched specs? (2026-09-20)

The user's question, asked before the last runs landed. Both prompts now have two runs on each
of the three patched specs (xjq v3, datagate v2, file_merger v7; jobs 247 to 258 and min13's
earlier pairs). Answer: the gap points the expected way and is noise at this size.

## By run

| problem | spectest+antislop (min13) | anti-slop |
|---|---|---|
| xjq v3 (167) | 167, 167 | 167, 167 |
| datagate v2 (405) | 393, 401 | 393, 396 |
| file_merger v7 (147) | 147, 147 | 146, 147 |
| all six runs (1438) | 1422 | 1416 |
| strict checkpoints (32) | 18 | 17 |

Mean of the three problems' fail rates: min13 0.66%, anti-slop 0.98%, a gap of 0.32 points, six
tests in 1438. An exact permutation test that reshuffles the four runs of each problem between
the two prompts (216 relabelings) gives the observed gap or more in 72 of them: one-sided p 0.33,
two-sided 0.67. Two runs of one cell already differ by up to 1.98 points (min13's own datagate
pair, 393 and 401), six times the gap between the prompts.

## By cause

A miss count overstates the evidence, because misses come in blocks from one choice. Causes per
run, leaving out the two every prompt shares on datagate v2 (the whitespace tests and the
corrupt-xls pair, the benchmark's):

| run | own causes | tests |
|---|---|---|
| min13 datagate 393 | a delimiter-free file is a 400 | 10 |
| min13 datagate 401 | none | 0 |
| anti-slop datagate 393 | a delimiter-free file is a 400 | 10 |
| anti-slop datagate 396 | an empty `ORIGIN_ALLOWLIST` is a configuration error | 3 |
| anti-slop file_merger 146 | the partition column's name is percent-encoded too | 1 |
| every other run | none | 0 |

One own cause in six runs for min13, three in six for anti-slop. That is the same direction
again and still three events against one. The delimiter choice, the largest block, fell once on
each side.

## What would settle it

With a per-run spread of about 0.4 points, seeing a 0.3-point gap at 80% power takes about 25
runs per prompt per problem, some 150 runs and $2,500. Not worth buying directly. Cheaper
evidence on the way: mvvault v1, where min13 is 227 of 227 once (job 262 is the repeat) and
anti-slop's pair (jobs 265, 266) runs if the repeat is strict. anti-slop fetched with `requests`
on v0 and lost seven tests to it; v1's urllib sentence removes that, so mvvault will show whether
a gap survives on a larger problem. One thing that does look real and is not a solve rate: the
three anti-slop-rule runs of four on datagate v2 that refuse an input every other prompt accepts
(`notes/spectest-datagate-runs.md`).

## At v0, for contrast

On the unpatched specs the gap is larger and part of it is reproducible: xjq 155 and 155 for
anti-slop against 162 and 162 for min13, the same twelve misses both times, one reading that
v3's sentences settle. Patching the spec removes the difference the registry was buying.
