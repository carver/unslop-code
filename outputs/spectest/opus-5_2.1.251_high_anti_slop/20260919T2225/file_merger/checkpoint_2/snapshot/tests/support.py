"""Shared scaffolding for the end-to-end tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import merge_files


class MergeTestCase(unittest.TestCase):
    """Base case providing a scratch directory and a `run` helper."""

    def setUp(self) -> None:
        self._workspace = TemporaryDirectory()
        self.addCleanup(self._workspace.cleanup)
        self.root = Path(self._workspace.name)

    def write(self, name: str, text: str) -> str:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def run_merge(self, *argv: str) -> list[str]:
        """Run the CLI, assert success, and return the output file's lines."""
        output = self.root / "out.csv"
        exit_code = merge_files.main(["--output", str(output), *argv])
        self.assertEqual(exit_code, 0)
        return output.read_text(encoding="utf-8").splitlines()
