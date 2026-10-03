# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import ask, workbench

class AskTests(unittest.TestCase):
    def test_prompt_is_explicitly_read_only(self):
        p=ask.build_prompt("Why?", "normal")
        self.assertIn("Do not modify files",p); self.assertIn("Do not use network access",p)
    def test_empty_question_rejected(self):
        with self.assertRaises(ValueError): ask.build_prompt(" ")
    def test_ask_uses_read_only_transport(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); trace=type("R",(),{"end_answer":"answer"})()
            with patch.object(ask,"run_codex_exec_json",return_value=trace) as run:
                d=ask.ask(workdir=root,question="Why?",log_root=root/"logs")
            self.assertEqual(d["answer"],"answer"); self.assertEqual(run.call_args.kwargs["sandbox"],"read-only"); self.assertFalse(run.call_args.kwargs["network_access"])
    def test_generated_plan(self):
        self.assertEqual(workbench.generated_plan("First\n\nSecond"),"1. ***Task***: First\n2. ***Task***: Second\n")

if __name__=="__main__": unittest.main()
