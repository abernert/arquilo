# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Exercise the confidence reader from an isolated runtime ZIP, without Codex."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_runtime_zip import build_distribution


class ConfidencePackageTests(unittest.TestCase):
    def test_packaged_reader_works_outside_checkout_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "runtime.zip"
            build_distribution(archive, source=ROOT)
            runtime = root / "runtime"
            with zipfile.ZipFile(archive) as package:
                package.extractall(runtime)
            payload = {
                "verdict": "PASS", "issues": [], "confidence": 0.8,
                "confidence_reason": "Inspected the requested synthetic artifact.",
                "evidence": ["synthetic-result.md:1 matches the requested title."],
                "uncertainties": ["This fixture does not establish live model accuracy."],
                "suggested_checks": ["Inspect the artifact independently."],
            }
            source = root / "summary.json"
            original = json.dumps({"review_classification": payload}).encode("utf-8")
            source.write_bytes(original)
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            env["PYTHONUTF8"] = "1"
            result = subprocess.run(
                [sys.executable, "-B", str(runtime / "review_confidence.py"), str(source)],
                cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS | confidence medium (0.8; uncalibrated reviewer estimate)", result.stdout)
            self.assertIn("Suggested checks (not executed)", result.stdout)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse((runtime / "tests").exists())


if __name__ == "__main__":
    unittest.main()
