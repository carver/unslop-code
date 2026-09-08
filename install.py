#!/usr/bin/env python3
"""Sandbox setup for unslop-code-bench: the run queue. Idempotent; called by sandbox-setup/setup.py.

Installs pueue (a persistent one-at-a-time task queue; bin/queue wraps it) into
~/.local/bin if missing, and starts its daemon if it is not running. Then applies the
problem-set patches in patches/scb-problems/ to the cached problems (~/.cache/scbench/problems,
or SCBENCH_PROBLEMS_PATH), skipping any already applied; a re-downloaded cache gets them back.
"""
import os, pathlib, shutil, subprocess, urllib.request

VERSION = "v4.0.4"
BIN = pathlib.Path.home() / ".local" / "bin"
ROOT = pathlib.Path(__file__).resolve().parent
PROBLEMS = pathlib.Path(os.environ.get("SCBENCH_PROBLEMS_PATH", pathlib.Path.home() / ".cache" / "scbench" / "problems"))


def patch_problems():
    """Apply every patches/scb-problems/*.patch to the problem cache; -N skips ones already in."""
    if not PROBLEMS.is_dir():
        print(f"no problem cache at {PROBLEMS}; patches wait for the first download")
        return
    for patch in sorted((ROOT / "patches" / "scb-problems").glob("*.patch")):
        r = subprocess.run(["patch", "-p1", "-N", "-s", "-r", "-", "-d", str(PROBLEMS)], stdin=patch.open(), capture_output=True, text=True)
        state = "applied" if r.returncode == 0 else ("already applied" if "Reversed" in r.stdout or "previously applied" in r.stdout else f"FAILED: {r.stdout}{r.stderr}")
        print(f"{patch.name}: {state}")


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


if __name__ == "__main__":
    main()
