#!/usr/bin/env python3
"""Sandbox setup for unslop-code-bench: the run queue. Idempotent; called by sandbox-setup/setup.py.

Installs pueue (a persistent one-at-a-time task queue; bin/queue wraps it) into
~/.local/bin if missing, and starts its daemon if it is not running.
"""
import pathlib, shutil, subprocess, urllib.request

VERSION = "v4.0.4"
BIN = pathlib.Path.home() / ".local" / "bin"


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


if __name__ == "__main__":
    main()
