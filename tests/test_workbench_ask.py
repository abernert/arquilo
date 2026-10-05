# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline hardening regressions: no credentials, live models or project execution."""
import contextlib
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ask
from ask_policy import config_arguments, validate_metadata
import codex_policy
import codex_transport
from controller_state import PlanAuthority, PlanIntegrityError
import safe_io
from workbench import Application, Server
from workbench_files import WorkbenchError, digest, lease, strict_json, write_json
from workbench_plan import PlanService, generated_plan
from workspace_reader import WorkspaceReader
from workbench_jobs import Jobs


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.todo = self.work / "tasks.md"
        self.todo.write_text("1. ***Task***: Create a small result.\n", encoding="utf-8")
        self.plan = PlanService(self.work, self.todo, self.root / "private")


class PlanTests(Fixture):
    def test_valid_preview_does_not_write(self):
        before = self.todo.read_bytes()
        p = self.plan.preview(generated_plan("Second", before.decode()), self.plan.view()["revision"])
        self.assertTrue(p["valid"])
        self.assertIn("+2. ***Task***: Second", p["diff"])
        self.assertEqual(self.todo.read_bytes(), before)

    def test_duplicates_rejected_before_save(self):
        before = self.todo.read_bytes()
        invalid = before.decode() + "1. ***Task***: Duplicate\n"
        self.assertFalse(self.plan.preview(invalid, digest(before))["valid"])
        with self.assertRaises(WorkbenchError):
            self.plan.save(invalid, digest(before))
        self.assertEqual(self.todo.read_bytes(), before)

    def test_unknown_directives_rejected(self):
        p = self.plan.preview("***CFG sandbox=danger-full-access***\n1. ***Task***: X\n", self.plan.view()["revision"])
        self.assertFalse(p["valid"])

    def test_alphanumeric_id_not_silently_ignored(self):
        p = self.plan.preview("T1. ***Task***: X\n", self.plan.view()["revision"])
        self.assertFalse(p["valid"])

    def test_stale_revision_cannot_overwrite(self):
        revision = self.plan.view()["revision"]
        self.todo.write_text("1. ***Task***: Changed externally\n")
        with self.assertRaises(WorkbenchError) as exc:
            self.plan.save("1. ***Task***: My stale copy\n", revision)
        self.assertEqual(exc.exception.status, 409)
        self.assertIn("externally", self.todo.read_text())

    def test_bom_crlf_comments_and_fenced_examples_preserved(self):
        original = "\ufeff# Goal\r\n<!-- comment -->\r\n```md\r\n99. Task: example\r\n```\r\n1. ***Task***: Real\r\n"
        self.todo.write_bytes(original.encode())
        view = self.plan.view()
        browser = original.lstrip("\ufeff").replace("\r\n", "\n").replace("Real", "Edited")
        self.plan.save(browser, view["revision"])
        self.assertEqual(self.todo.read_bytes(), original.replace("Real", "Edited").encode())
        self.assertEqual(len(self.plan.view()["tasks"]), 1)
        self.assertEqual(len(list((self.plan.private / "edits").glob("*/before.md"))), 1)

    def test_generate_appends_and_never_renumbers(self):
        original = "# Intro\n5. ***Task***: Existing\n5.1. ***Task***: Child\n"
        value = generated_plan("Next\nThen", original)
        self.assertTrue(value.startswith(original))
        self.assertIn("6. ***Task***: Next", value)
        self.assertIn("7. ***Task***: Then", value)

    def test_controller_lock_blocks_save(self):
        authority = PlanAuthority(self.todo, self.plan.state)
        try:
            with self.assertRaises(WorkbenchError):
                self.plan.save("1. ***Task***: Edited\n", self.plan.view()["revision"])
        finally:
            authority.close()

    def test_explicit_owner_adoption_is_separate(self):
        authority = PlanAuthority(self.todo, self.plan.state)
        authority.close()
        self.plan.save("1. ***Task***: Edited\n", self.plan.view()["revision"])
        self.assertTrue(self.plan.view()["needs_owner_adoption"])
        with self.assertRaises(PlanIntegrityError):
            PlanAuthority(self.todo, self.plan.state)

    def test_start_revision_checked_before_adoption(self):
        authority = PlanAuthority(self.todo, self.plan.state)
        authority.close()
        before = (self.plan.state / "plan.json").read_bytes()
        wrong = "0" * 64
        self.todo.write_text("1. ***Task***: Edited\n")
        with self.assertRaises(PlanIntegrityError):
            PlanAuthority(self.todo, self.plan.state, accept_changes=True, expected_sha256=wrong)
        self.assertEqual((self.plan.state / "plan.json").read_bytes(), before)

    def test_concurrent_saves_one_wins(self):
        rev = self.plan.view()["revision"]
        gate = threading.Barrier(2)
        outcomes = []
        def save(title):
            gate.wait()
            try:
                self.plan.save(f"1. ***Task***: {title}\n", rev)
                outcomes.append("saved")
            except WorkbenchError:
                outcomes.append("conflict")
        threads = [threading.Thread(target=save, args=(str(i),)) for i in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertCountEqual(outcomes, ["saved", "conflict"])

    def test_symlink_and_hardlink_plan_refused(self):
        target = self.work / "target.md"
        target.write_text("Do not change")
        self.todo.unlink()
        try:
            self.todo.symlink_to(target)
        except OSError:
            self.skipTest("Symlinks unavailable")
        with self.assertRaises((OSError, ValueError)): self.plan.view()
        self.todo.unlink()
        os.link(target, self.todo)
        with self.assertRaises((OSError, ValueError)): self.plan.view()
        self.assertEqual(target.read_text(), "Do not change")


class ReaderTests(Fixture):
    def test_hidden_credentials_and_binary_not_in_inventory(self):
        (self.work / ".env").write_text("SECRET")
        (self.work / "credentials.json").write_text("SECRET")
        (self.work / "image.png").write_bytes(b"\x00")
        reader = WorkspaceReader(self.work)
        self.assertEqual(reader.inventory, ["tasks.md"])

    def test_traversal_absolute_and_nontext_denied(self):
        reader = WorkspaceReader(self.work)
        for path in ("../outside.md", str(self.todo), ".env", "tasks.md; echo leak", "C:\\secret.txt"):
            with self.subTest(path=path), self.assertRaises(WorkbenchError): reader.read(path)

    def test_source_hash_and_changed_versions(self):
        reader = WorkspaceReader(self.work)
        source = reader.read("tasks.md")
        self.todo.write_text("new contents")
        self.assertEqual(reader.read("tasks.md")["sha256"], source["sha256"])
        self.assertEqual(reader.changed(), ["tasks.md"])

    def test_read_size_and_range_bounded(self):
        reader = WorkspaceReader(self.work, total_limit=2)
        with self.assertRaises(WorkbenchError): reader.read("tasks.md")
        reader = WorkspaceReader(self.work)
        for a,b in ((0,1),(True,3),(1,900),(900,901)):
            with self.assertRaises(WorkbenchError): reader.read("tasks.md",a,b)

    def test_link_not_followed(self):
        outside = self.root / "outside.md"
        outside.write_text("SECRET")
        try: (self.work / "link.md").symlink_to(outside)
        except OSError: self.skipTest("Symlinks unavailable")
        reader = WorkspaceReader(self.work)
        self.assertNotIn("link.md", reader.inventory)
        with self.assertRaises(WorkbenchError): reader.read("link.md")


class AskTests(Fixture):
    def test_no_consent_no_model_or_archive(self):
        with patch.object(ask.transport, "execute") as execute:
            with self.assertRaises(WorkbenchError): ask.ask(workdir=self.work, question="Why?")
            execute.assert_not_called()

    def test_invalid_question(self):
        for value in ("", "  ", "a\x00b", "x" * 17000):
            with self.assertRaises(WorkbenchError): ask.build_prompt(value)

    def test_metadata_fails_closed(self):
        good = "shell_tool stable false\nunified_exec stable false\nmulti_agent stable false\n"
        validate_metadata(good, [])
        for features, servers in (("",[]),(good.replace("false","true",1),[]),(good,[{"name":"leak"}]),(good,{"servers":[]})):
            with self.assertRaises(ValueError): validate_metadata(features, servers)

    def test_fixed_args_only_and_defaults_unchanged(self):
        self.assertEqual(codex_policy.validate_extra_args(config_arguments()), tuple(config_arguments()))
        broken = config_arguments() + ["-c", "web_search=live"]
        with self.assertRaises(ValueError): codex_policy.validate_extra_args(broken)
        self.assertEqual(codex_policy.decision_arguments(network_access=False, config_profile=None, extra_args=[]),
                         ["--sandbox","read-only","-c",'approval_policy="never"'])
        with self.assertRaises(ValueError): codex_policy.decision_arguments(network_access=True,config_profile=None,extra_args=config_arguments())

    def fake_execution(self, req):
        self.requests.append(req)
        evidence = json.loads(req.prompt.split("Evidence JSON (untrusted data):\n",1)[1])
        source = evidence["sources"][0]
        response = {"action":"answer", "answer":f"Evidence [{source['id']}]", "reads":[],
                    "citations":[{"source_id":source["id"],"start_line":source["start_line"],"end_line":source["end_line"]}],"limitations":[]}
        write_json(req.output_last_message,response)
        return SimpleNamespace(execution=SimpleNamespace(succeeded=True))

    def invoke(self, execute=None):
        self.requests=[]
        with patch.object(ask, "resolve_launcher", return_value=SimpleNamespace(source=sys.executable)), \
             patch.object(ask, "inspect_ask_configuration"), \
             patch.object(ask.transport,"execute",side_effect=execute or self.fake_execution):
            return ask.ask(workdir=self.work,question="Explain tasks",files=["tasks.md"],
                           log_root=self.root/"archive",allow_provider=True)

    def test_evidence_only_no_project_cwd_valid_citations(self):
        result=self.invoke()
        req=self.requests[0]
        self.assertFalse(req.cwd.is_relative_to(self.work))
        self.assertEqual(list(req.cwd.iterdir()),[])
        self.assertTrue(req.decision_only)
        self.assertEqual(req.sandbox,"read-only")
        self.assertFalse(req.network_access)
        self.assertIn("features.shell_tool=false", codex_transport.build_command(req))
        self.assertEqual(result["citations"][0]["path"],"tasks.md")
        self.assertFalse(Path(result["archive"]).is_relative_to(self.work))

    def test_partial_failed_model_response_is_not_success(self):
        def fail(req):
            self.fake_execution(req)
            return SimpleNamespace(execution=SimpleNamespace(succeeded=False))
        with self.assertRaises(RuntimeError):self.invoke(fail)
        manifest=list((self.root/"archive").glob("*/ask.json"))[0]
        self.assertEqual(json.loads(manifest.read_text())["status"],"failed")

    def test_unknown_citation_rejected(self):
        def invalid(req):
            result=self.fake_execution(req)
            data=json.loads(req.output_last_message.read_text())
            data["citations"][0]["source_id"]="S0000000000000000"
            write_json(req.output_last_message,data)
            return result
        with self.assertRaises(WorkbenchError):self.invoke(invalid)

    def test_missing_response_not_recovered_from_stdout(self):
        with self.assertRaises(FileNotFoundError):
            self.invoke(lambda req: SimpleNamespace(execution=SimpleNamespace(succeeded=True),trace=SimpleNamespace(end_answer="guessed")))

    def test_archive_inside_project_refused(self):
        with self.assertRaises(WorkbenchError):ask.ask(workdir=self.work,question="Why?",log_root=self.work/"logs",allow_provider=True)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError):strict_json('{"action":"answer","action":"read"}')


class HttpTests(Fixture):
    def setUp(self):
        super().setUp()
        self.app=Application(self.plan)
        self.server=Server(self.app,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.app.jobs.shutdown()

    def request(self,path="/api/state",method="GET",body=None,extra=None,token=True):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        headers={"Host":self.server.authority}
        if token:headers["Authorization"]="Bearer "+self.server.token
        if method=="POST":headers.update({"Origin":self.server.origin,"Content-Type":"application/json"})
        headers.update(extra or {})
        conn.request(method,path,body=body,headers=headers)
        r=conn.getresponse(); data=r.read(); status=r.status; resultheaders=dict(r.getheaders());conn.close()
        return status,data,resultheaders

    def test_static_page_has_no_project_data_or_token(self):
        code,data,headers=self.request("/",token=False)
        self.assertEqual(code,200)
        self.assertNotIn(str(self.work).encode(),data)
        self.assertNotIn(self.server.token.encode(),data)
        self.assertIn("frame-ancestors 'none'",headers["Content-Security-Policy"])

    def test_no_token_no_state(self):
        self.assertEqual(self.request(token=False)[0],403)

    def test_host_dns_rebinding_blocked(self):
        self.assertEqual(self.request(extra={"Host":"attacker.invalid"})[0],403)

    def test_query_token_not_accepted(self):
        self.assertNotEqual(self.request("/api/state?token="+self.server.token,token=False)[0],200)

    def test_origin_and_csrf_blocked(self):
        for origin in ("https://attacker.invalid","null"):
            code,_,_=self.request("/api/plan/save","POST",'{}',{"Origin":origin})
            self.assertEqual(code,403)

    def test_malformed_json_and_media_type(self):
        self.assertEqual(self.request("/api/plan/save","POST",'{"text":"a","text":"b"}')[0],400)
        self.assertEqual(self.request("/api/plan/save","POST",'{}',{"Content-Type":"text/plain"})[0],415)

    def test_bounded_body(self):
        self.assertEqual(self.request("/api/plan/save","POST",b"{}",{"Content-Length":"2000000"})[0],413)

    def test_status_sequence_and_plan_revision(self):
        a=json.loads(self.request()[1]);b=json.loads(self.request()[1])
        self.assertGreater(b["sequence"],a["sequence"])
        self.assertEqual(a["plan"]["revision"],digest(self.todo.read_bytes()))

    def test_stale_save_via_http(self):
        body=json.dumps({"text":"1. ***Task***: Bad overwrite", "revision":"wrong"})
        self.assertEqual(self.request("/api/plan/save","POST",body)[0],409)

    def test_generate_is_draft_only(self):
        before=self.todo.read_bytes()
        body=json.dumps({"ideas":"Next", "base":before.decode(),"revision":digest(before)})
        code,data,_=self.request("/api/plan/generate","POST",body)
        self.assertEqual(code,200);self.assertTrue(json.loads(data)["valid"])
        self.assertEqual(self.todo.read_bytes(),before)

    def test_no_model_start_without_consent(self):
        body=json.dumps({"request_id":"1"*32,"question":"Why?","depth":"normal","allow_provider":False})
        with patch.object(self.app.jobs,"start") as start:
            self.assertEqual(self.request("/api/ask/start","POST",body)[0],403)
            start.assert_not_called()

    def test_action_get_not_executed(self):
        self.assertEqual(self.request("/api/run/cancel")[0],404)

    def test_unknown_fields_cannot_inject_argv(self):
        body=json.dumps({"request_id":"1"*32,"question":"Why?","depth":"normal","allow_provider":True,"extra_args":["--danger-full-access"]})
        self.assertEqual(self.request("/api/ask/start","POST",body)[0],400)


class ControllerTests(Fixture):
    def args(self):
        return ["--todo-file",str(self.todo),"--workdir",str(self.work),"--state-dir",str(self.root/"private"),"--skip-codex-preflight"]

    def test_pause_before_dispatch_is_not_completion(self):
        import workbench_controller
        events=[]
        with contextlib.redirect_stdout(io.StringIO()),patch.object(workbench_controller.run_todos,"_terminal_beep",create=True):
            code=workbench_controller.run(self.args(),revision=digest(self.todo.read_bytes()),pause_requested=lambda:True,
                cancel_requested=lambda:None,emit=lambda kind,data:events.append((kind,data)))
        self.assertEqual(code,9)
        self.assertTrue(any(k=="paused" for k,d in events))
        self.assertIn("***Task***",self.todo.read_text())
        self.assertFalse((self.work/"process_stop").exists())
        self.assertTrue(any(k=="controller_status" and d["status"]=="paused" for k,d in events))

    def test_expected_revision_mismatch_no_dispatch(self):
        import workbench_controller
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            code=workbench_controller.run(self.args(),revision="0"*64,pause_requested=lambda:False,
                                         cancel_requested=lambda:None,emit=lambda *x:None)
        self.assertNotEqual(code,0)
        self.assertIn("***Task***",self.todo.read_text())



class JobTests(Fixture):
    def setUp(self):
        super().setUp()
        self.jobs = Jobs(self.plan.private / "jobs")
        self.addCleanup(self.jobs.shutdown)

    def fake_popen(self, argv, **kwargs):
        job = Path(argv[-1])
        code = '''import json,sys,time,pathlib
p=pathlib.Path(sys.argv[1])
print("streamed before completion",flush=True)
while not (p/"finish").exists() and not (p/"cancel.request").exists():time.sleep(.02)
status="cancelled" if (p/"cancel.request").exists() else "completed"
(p/"worker.json").write_text(json.dumps({"status":status,"exit_code":0}))
'''
        return self.real_popen([sys.executable,"-u","-c",code,str(job)], **kwargs)

    def wait(self, fn):
        deadline=time.monotonic()+4
        while not fn() and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(fn())

    def test_stream_live_then_terminal_and_replay(self):
        self.real_popen=subprocess.Popen
        ident="a"*32; payload={"kind":"run","workdir":str(self.work),"arguments":[],"revision":"a"*64}
        with patch("workbench_jobs.subprocess.Popen",side_effect=self.fake_popen) as launch:
            first=self.jobs.start(ident,"run",payload)
            second=self.jobs.start(ident,"run",payload)
            self.assertEqual(first["id"],second["id"])
            self.assertEqual(launch.call_count,1)
            self.wait(lambda:"streamed" in self.jobs.snapshot("run").get("output",""))
            self.assertTrue(self.jobs.snapshot("run")["active"])
            safe_io.write_text(self.jobs.root/ident/"finish","done",exclusive=True)
            self.wait(lambda:not self.jobs.busy())
        self.assertEqual(self.jobs.snapshot("run")["status"],"completed")
        self.assertEqual(self.jobs.start(ident,"run",payload)["id"],ident)

    def test_cancel_retains_existing_stop_and_rejects_stale_id(self):
        self.real_popen=subprocess.Popen
        ident="b"*32; payload={"kind":"run","workdir":str(self.work),"arguments":[],"revision":"b"*64}
        existing=self.work/"process_stop";existing.write_text("Original independent reason")
        with patch("workbench_jobs.subprocess.Popen",side_effect=self.fake_popen):
            self.jobs.start(ident,"run",payload)
            with self.assertRaises(WorkbenchError):self.jobs.control("run","c"*32,"cancel")
            self.jobs.control("run",ident,"cancel")
            self.wait(lambda:not self.jobs.busy())
        self.assertEqual(existing.read_text(),"Original independent reason")
        self.assertEqual(self.jobs.snapshot("run")["status"],"cancelled")

    def test_id_reuse_different_request_rejected(self):
        self.real_popen=subprocess.Popen
        ident="c"*32; payload={"kind":"run","workdir":str(self.work),"arguments":[],"revision":"c"*64}
        with patch("workbench_jobs.subprocess.Popen",side_effect=self.fake_popen):
            self.jobs.start(ident,"run",payload)
            with self.assertRaises(WorkbenchError):self.jobs.start(ident,"run",{**payload,"revision":"d"*64})
            self.jobs.control("run",ident,"cancel")
            self.wait(lambda:not self.jobs.busy())

    def test_exit_zero_without_manifest_not_success(self):
        self.real_popen=subprocess.Popen
        def no_manifest(argv,**kwargs):return self.real_popen([sys.executable,"-c","print('done')"],**kwargs)
        with patch("workbench_jobs.subprocess.Popen",side_effect=no_manifest):
            self.jobs.start("d"*32,"run",{"kind":"run","workdir":str(self.work)})
            self.wait(lambda:not self.jobs.busy())
        self.assertEqual(self.jobs.snapshot("run")["status"],"failed")

    def test_restart_does_not_adopt_pid_as_live_process(self):
        ident="e"*32;path=self.jobs.root/ident;path.mkdir()
        write_json(path/"job.json",{"id":ident,"kind":"run","status":"running","pid":os.getpid(),"started_at":"2026-01-01"})
        restarted=Jobs(self.jobs.root)
        self.assertFalse(restarted.busy())
        self.assertEqual(restarted.snapshot("run")["status"],"interrupted")

    def test_parallel_start_one_owned_process(self):
        self.real_popen=subprocess.Popen
        barrier=threading.Barrier(2);results=[]
        def start(ident):
            barrier.wait()
            try:results.append(self.jobs.start(ident,"run",{"kind":"run","workdir":str(self.work)}))
            except WorkbenchError:results.append("busy")
        with patch("workbench_jobs.subprocess.Popen",side_effect=self.fake_popen) as launch:
            threads=[threading.Thread(target=start,args=(x*32,)) for x in "ab"]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertEqual(launch.call_count,1)
            self.assertIn("busy",results)
            self.jobs.control("run",self.jobs.snapshot("run")["id"],"cancel")
            self.wait(lambda:not self.jobs.busy())

class MoreBoundaryTests(Fixture):
    def test_active_run_blocks_editor_and_draft_generation(self):
        app=Application(self.plan)
        with patch.object(app.jobs,"busy",return_value=True):
            for route,body in (("/api/plan/save",{"text":"new","revision":self.plan.view()["revision"]}),
                               ("/api/plan/generate",{"ideas":"new","base":"","revision":self.plan.view()["revision"]})):
                with self.assertRaises(WorkbenchError) as exc:app.action(route,body)
                self.assertEqual(exc.exception.status,409)

    def test_cancel_propagates_to_active_subworkspace(self):
        import workbench_controller
        import run_todos
        child=self.work/"child";child.mkdir()
        cancellation=threading.Event()
        events=[]
        def fake_autobuild(runner,identifier,text,**kwargs):
            cancellation.set()
            marker=kwargs["process_stop_override"]
            deadline=time.monotonic()+3
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(marker.exists())
            return run_todos.TaskOutcome(completed=False,process_stop_triggered=True,message="Cancelled")
        def fake_handle(runner,todo):
            return runner._run_autobuild(todo.identifier,"synthetic",process_stop_override=child/"process_stop")
        args=["--todo-file",str(self.todo),"--workdir",str(self.work),"--state-dir",str(self.root/"private"),"--skip-codex-preflight"]
        with patch.object(run_todos.TodoRunner,"_run_autobuild",fake_autobuild), \
             patch.object(run_todos.TodoRunner,"_handle_todo",fake_handle),contextlib.redirect_stdout(io.StringIO()):
            code=workbench_controller.run(args,revision=digest(self.todo.read_bytes()),pause_requested=lambda:False,
                cancel_requested=lambda:"cancel" if cancellation.is_set() else None,emit=lambda *x:events.append(x))
        self.assertEqual(code,6)
        self.assertIn("***Task***",self.todo.read_text())
        self.assertTrue((child/"process_stop").exists())

    def test_pause_after_current_task_never_dispatches_next(self):
        import workbench_controller
        import run_todos
        self.todo.write_text("1. ***Task***: First\n2. ***Task***: Second\n")
        paused=threading.Event();seen=[]
        def fake_handle(runner,todo):
            seen.append(todo.identifier)
            runner._mark_todo_as_done(todo)
            paused.set()
            return run_todos.TaskOutcome(completed=True,message="synthetic completed")
        args=["--todo-file",str(self.todo),"--workdir",str(self.work),"--state-dir",str(self.root/"private"),"--skip-codex-preflight"]
        with patch.object(run_todos.TodoRunner,"_handle_todo",fake_handle),contextlib.redirect_stdout(io.StringIO()):
            code=workbench_controller.run(args,revision=digest(self.todo.read_bytes()),pause_requested=paused.is_set,
                cancel_requested=lambda:None,emit=lambda *x:None)
        self.assertEqual(code,9);self.assertEqual(seen,["1"])
        self.assertIn("2. ***Task***",self.todo.read_text())

    def test_large_output_is_drained_but_bounded(self):
        jobs=Jobs(self.plan.private/"jobs");original=subprocess.Popen
        def process(argv,**kwargs):
            code="import sys,pathlib,json;p=pathlib.Path(sys.argv[1]);print('x'*9000000,flush=True);(p/'worker.json').write_text(json.dumps({'status':'completed'}))"
            return original([sys.executable,"-u","-c",code,argv[-1]],**kwargs)
        with patch("workbench_jobs.subprocess.Popen",side_effect=process):
            jobs.start("f"*32,"run",{"kind":"run","workdir":str(self.work)})
            deadline=time.monotonic()+5
            while jobs.busy() and time.monotonic()<deadline:time.sleep(.02)
        self.assertFalse(jobs.busy())
        self.assertLessEqual(len(jobs.snapshot("run")["output"]),24000)
        self.assertTrue(jobs.snapshot("run")["output_truncated"])
        self.assertLessEqual((jobs.root/("f"*32)/"console.log").stat().st_size,8*1024*1024)
        jobs.shutdown()

    def test_ui_script_never_renders_untrusted_html(self):
        from workbench_assets import JS
        self.assertNotIn("innerHTML",JS)
        self.assertIn("textContent",JS)
        self.assertIn("setTimeout(poll,1000)",JS)
        self.assertIn("history.replaceState",JS)


if __name__ == "__main__":unittest.main()
