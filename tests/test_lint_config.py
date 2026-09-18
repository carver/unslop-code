"""ruff only sees the extensionless bin scripts that ruff.toml lists; a new one must be added."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def python_scripts():
    return sorted(f"bin/{p.name}" for p in (ROOT / "bin").iterdir()
                  if p.is_file() and p.read_bytes().startswith(b"#!/usr/bin/env python"))


def test_every_python_bin_script_is_listed_for_ruff():
    listed = tomllib.loads((ROOT / "ruff.toml").read_text())["extend-include"]
    assert sorted(listed) == python_scripts()
