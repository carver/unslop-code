# rejector: the v0 misses, by sentence (2026-09-20)

Step 1 and the first half of step 2 of `/solve-one-problem`, from the nine opus-5 runs on the
unpatched spec (just-solve 73 and 76, anti-slop 73, min11 74 and 76, min12 75 and 76, min13 74
and 73, of 79). Eleven tests fail somewhere; the score gap between prompts is inside the bare
prompt's own spread. Counts are over those nine runs. Drafts for 1 to 6 sit uncommitted in
`specs/drafts/`, each with its evidence; nothing is built.

## Readings

1. **"Retry it up to 3 times. After the third failure"** (checkpoint_1.md:145). The tests count
   three HTTP calls in all; six runs make four (one call and three retries), and the fourth
   reaches the mock's default reply, so the doomed row comes back with an output.
   `test_api_failure_after_max_retries`, 3 pass, 6 fail. The highest Risk on the problem, 40 to
   45 in every spectest registry; the sentence's two halves disagree and the tests take the
   second.
2. **"The stdout summary now includes a `tasks` object"** (checkpoint_2.md:184). For a single-task
   config the tests want the part 1 summary, no `tasks`. `test_backward_compat_single_task`,
   4 pass, 5 fail. Risk 35 in every spectest run, 45 in min11's.
3. **Replies pair with rows in input order** (no sentence until checkpoint_5.md:52). The mock
   serves queued replies first come, first served; `test_first_number_extract` at checkpoint 2
   needs the first row's request to arrive first, while checkpoint 1 demands concurrency and is
   silent on order. 5 pass, 4 fail, different runs each time: a race the spec's rule arrives three
   checkpoints too late to prevent, and that no sentence can fully close. No registry asks.
4. **A malformed ICL line is "not valid JSON"** (checkpoint_3.md:60). The run must exit 1 before
   any request, which every run does; the test also wants that phrase in stderr, and no spec line
   words any error. `test_invalid_icl_file_fails_before_any_api_requests`, 5 pass, 4 fail.
5. **A row that hits `max_iterations` has `passed: false`** (checkpoint_4.md:90 against :190).
   The spec says an agentic row with no evaluation keeps `result.passed` null; the test has no
   evaluation and wants false. `test_agentic_max_iterations`, 1 pass, 8 fail. The test contradicts
   the spec; the runs followed the spec.
6. **`est_time_minutes` is not rounded to the example's one decimal** (checkpoint_5.md:236). One
   row at rpm 60 is 0.0167 minutes; the test wants 0.016 to 0.017 and every run prints 0.0,
   copying the example's `9.3`. `test_dry_run`, 0 pass, 9 fail.

1 and 2 are readings. 3, 5 and 6 are the benchmark's mistakes (a rule stated late, a test against
the spec's own sentence, a misleading example). 4 is a literal phrase the spec never gives, the
same kind as mvvault's fetch-failure message.

## Open: `test_tpm_gate`

4 pass, 5 fail, by timeout: `--tpm 50`, two requests that each reserve 31 tokens, a 10-second
limit. The second request can only go once the first reply has turned its reservation of 31 into
the actual 10. The failing runs wait out the 60-second window instead. It is not the registered
question: min12's repeat (T86) and min13's second run (T84, Risk 35) both chose "the reservation
is replaced by the actual usage", the tests' reading, and min12's repeat still timed out. Needs
the limiter code of a failing run read, or `bin/askrun`. No draft.

## Singles

`test_costs` (min13's first run: 0.011 against 0.01, a rounding of money) and
`test_llm_judge_pass` (min13's repeat). One run each; noise until they recur.
