import subprocess
import sys
import unittest
from pathlib import Path

from sutra_lang import __version__

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sutra_lang", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


class CliSmokeTests(unittest.TestCase):
    def test_version(self) -> None:
        result = run_cli("--version")

        self.assertEqual(result.returncode, 0)
        self.assertIn(f"SUTRA {__version__}", result.stdout)

    def test_help(self) -> None:
        result = run_cli("--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: sutra", result.stdout)
        self.assertIn("run", result.stdout)
        self.assertIn("demo", result.stdout)

    def test_parse_example(self) -> None:
        result = run_cli("parse", "examples/buyer.sutra")

        self.assertEqual(result.returncode, 0)
        self.assertIn("SUTRA AST", result.stdout)

    def test_demo_completes(self) -> None:
        result = run_cli("demo")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Transaction complete", result.stdout)
