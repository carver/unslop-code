#!/usr/bin/env python3
"""Sandbox setup for unslop-code-bench: the run queue and the harness. Idempotent; called by
sandbox-setup/setup.py.

Installs pueue (a persistent one-at-a-time task queue; bin/queue wraps it) into
~/.local/bin if missing, and starts its daemon if it is not running. Applies the
problem-set patches in patches/scb-problems/ to the cached problems (~/.cache/scbench/problems,
or SCBENCH_PROBLEMS_PATH), skipping any already applied; a re-downloaded cache gets them back.
Then builds the harness the runs use: a clone of slop-code-bench at harness/ (not tracked),
pinned to HARNESS_COMMIT with the six source patches from patches/ applied in README order,
and its venv at ~/.venvs/scbench-harness, which bin/scb runs. The clone at slop-code-bench/
is for developing the harness and is left alone: on 2026-09-11 a branch switch there dropped
the patches under a running queue, which is why runs read a checkout of their own.
"""
import os
import pathlib
import shutil
import subprocess
import urllib.request

VERSION = "v4.0.4"
BIN = pathlib.Path.home() / ".local" / "bin"
ROOT = pathlib.Path(__file__).resolve().parent
PROBLEMS = pathlib.Path(os.environ.get("SCBENCH_PROBLEMS_PATH", pathlib.Path.home() / ".cache" / "scbench" / "problems"))
HARNESS_URL = "https://github.com/SprocketLab/slop-code-bench.git"
HARNESS_COMMIT = "06b5c0687d4c05ee502e9696a4d0c22fc1eec5e0"  # "Forgot sonnet 5", the base the patches were cut against
HARNESS = ROOT / "harness"
HARNESS_VENV = pathlib.Path.home() / ".venvs" / "scbench-harness"
HARNESS_PATCHES = [ROOT / "patches" / f"{name}.patch" for name in (
    "claude-code-stream-parser-string-message",
    "stop-after-checkpoint",
    "agent-death-detection-and-prompt-context",
    "resume-invalidate-infra-failed-checkpoints",
    "container-init-and-timeout-kill",
    "retry-keeps-every-attempt-transcript",
)]


def apply_patch(patch, tree):
    """Apply one unified diff under `tree`; 'applied', 'already applied', or 'failed: <why>'."""
    r = subprocess.run(["patch", "-p1", "-N", "-s", "-r", "-", "-d", str(tree)], stdin=patch.open(), capture_output=True, text=True)
    if r.returncode == 0:
        return "applied"
    if "Reversed" in r.stdout or "previously applied" in r.stdout:
        return "already applied"
    return f"failed: {(r.stdout + r.stderr).strip()[-300:]}"


def patch_problems():
    """Apply every patches/scb-problems/*.patch to the problem cache."""
    if not PROBLEMS.is_dir():
        print(f"no problem cache at {PROBLEMS}; patches wait for the first download")
        return
    for patch in sorted((ROOT / "patches" / "scb-problems").glob("*.patch")):
        print(f"{patch.name}: {apply_patch(patch, PROBLEMS)}")


def git(*args):
    return subprocess.run(["git", "-C", str(HARNESS), *args], capture_output=True, text=True, check=True).stdout.strip()


def install_harness():
    """The pinned, patched harness checkout and its venv; a checkout moved off the pin is left alone."""
    if not (HARNESS / ".git").is_dir():
        print(f"cloning the harness into {HARNESS}")
        subprocess.run(["git", "clone", "-q", HARNESS_URL, str(HARNESS)], check=True)
        git("checkout", "-q", HARNESS_COMMIT)
    head = git("rev-parse", "HEAD")
    if head != HARNESS_COMMIT:
        print(f"harness at {head[:7]}, pinned to {HARNESS_COMMIT[:7]}; leaving it (git -C harness checkout {HARNESS_COMMIT[:7]} to re-pin)")
        return
    for patch in HARNESS_PATCHES:
        state = apply_patch(patch, HARNESS)
        print(f"harness {patch.name}: {state}")
        if state.startswith("failed"):
            raise SystemExit(f"install: {patch.name} does not apply to the harness at {HARNESS_COMMIT[:7]}")
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(HARNESS_VENV)}
    subprocess.run(["uv", "sync", "-q", "--project", str(HARNESS)], env=env, check=True)
    print(f"harness venv at {HARNESS_VENV}")


def main():
    BIN.mkdir(parents=True, exist_ok=True)
    for name in ("pueue", "pueued"):
        dst = BIN / name
        if not dst.exists():
            url = f"https://github.com/Nukesor/pueue/releases/download/{VERSION}/{name}-x86_64-unknown-linux-musl"
            print(f"installing {name} {VERSION}")
            with urllib.request.urlopen(url, timeout=60) as r, dst.open("wb") as f:
                shutil.copyfileobj(r, f)
            dst.chmod(0o755)
    if subprocess.run([BIN / "pueue", "status"], capture_output=True).returncode != 0:
        print("starting pueued")
        subprocess.run([BIN / "pueued", "-d"], check=True)
    patch_problems()
    install_harness()


if __name__ == "__main__":
    main()
