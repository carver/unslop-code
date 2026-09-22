"""Helpers shared by the test modules."""

from config import load_config

MULTI_CONFIG = """
defaults:
  api_url: "http://example.invalid"
  model: "mock-model"
  output_field: "solution"
  prompt:
    user: "{question}"
  rate_limits:
    rpm: 100
    tpm: 50000
    max_concurrent: 10
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
    budget: 50.0

tasks:
  code_gen:
    rate_limits:
      tpm: 30000
    cost:
      prompt_cost_per_1k: 0.005
  gsm8k: {}
"""


def load_multi(tmp_path, overrides=None):
    """Load :data:`MULTI_CONFIG` and return its tasks by name."""
    path = tmp_path / "multi.yaml"
    path.write_text(MULTI_CONFIG, encoding="utf-8")
    flags = {"rpm": None, "tpm": None, "max_concurrent": None, "budget": None}
    config = load_config(str(path), {**flags, **(overrides or {})})
    return {task.name: task for task in config.tasks}
