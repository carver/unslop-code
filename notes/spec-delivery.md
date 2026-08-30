# Spec delivery at checkpoint k: delta only

Checked against dev-set problem `xjq` (5 checkpoints) in scb-problems v1.0
(commit 4d38d300). No holdout spec text was read.

## Mechanism

1. `ProblemConfig.get_checkpoint_spec()` reads exactly one file per checkpoint
   (`src/slop_code/evaluation/config.py:849-858`):

   ```python
   # Read from {checkpoint_name}.md at problem root
   spec_file = self.path / f"{checkpoint_name}.md"
   ...
   return spec_file.read_text()
   ```

2. The runner passes that single file's text as `spec_text`
   (`src/slop_code/agent_runner/runner.py:420`):

   ```python
   spec_text=problem.get_checkpoint_spec(checkpoint.name),
   ```

   and renders it with `is_continuation = not is_first_checkpoint`
   (`runner.py:207`). Nothing concatenates earlier checkpoint files.

3. `configs/prompts/just-solve.jinja` only branches on `is_continuation` to
   change the venv/requirements sentence, then emits `{{ spec.strip() }}`:

   ```jinja
   {% if not is_continuation -%}
   Use a virtual environment and ensure that a `requirements.txt` is present ...
   {% else -%}
   Keep using the same virtual environment you started with, update `requirements.txt` ...
   {% endif -%}

   Your task is:
   {{ spec.strip() }}
   ```

4. Each checkpoint is a fresh `claude --print` process (no `--continue`;
   that flag is only used on the in-checkpoint retry path,
   `agent.py:791`). What carries over is the workspace directory (the
   agent's files from checkpoint k-1), not the conversation and not the
   earlier spec text.

## Empirical check

Line overlap between consecutive `checkpoint_k.md` files for `xjq`, ignoring
blank lines:

| transition | prior lines reappearing | new lines |
|---|---|---|
| 1 -> 2 | 3 / 21 (14%) | 23 |
| 2 -> 3 | 3 / 26 (12%) | 20 |
| 3 -> 4 | 3 / 23 (13%) | 16 |
| 4 -> 5 | 3 / 19 (16%) | 31 |

The 3 shared lines are the training-data canary comment at the top of every
file. So each checkpoint file is the new requirements only.

## Consequence for the experiment

At checkpoint k the agent sees: the delta spec for k, plus whatever it left
in the workspace. It does not see the cumulative spec. Regression tests from
earlier checkpoints still run at eval time (`include_prior_tests: true` on
every xjq checkpoint), so the agent is graded on requirements it can no
longer read. That gap is the mechanism behind the Strict vs Isolated Solve
spread.
