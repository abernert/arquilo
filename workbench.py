# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Local, dependency-free ARQUILO browser workbench."""
from __future__ import annotations
import argparse, html, json, secrets, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from ask import ask
from todo_syntax import task_headers

def generated_plan(text:str)->str:
    items=[x.strip() for x in text.splitlines() if x.strip()]
    return "\n".join(f"{i}. ***Task***: {item}" for i,item in enumerate(items,1))+("\n" if items else "")

class State:
    def __init__(self,workdir:Path,todo:Path,token:str):
        self.workdir,self.todo,self.token=workdir,todo,token; self.lock=threading.Lock(); self.run=None; self.run_output=""; self.ask_answer=""
    def tasks(self):
        if not self.todo.exists(): return []
        text=self.todo.read_text(encoding="utf-8")
        return [{"id":m.group(1).strip(),"status":m.group(2).strip("*"),"text":m.group(3)} for _,m in task_headers(text)]

def page(s:State,message="")->bytes:
    tasks="".join(f"<tr><td>{html.escape(t['id'])}</td><td>{html.escape(t['status'])}</td><td>{html.escape(t['text'])}</td></tr>" for t in s.tasks()) or "<tr><td colspan=3>No tasks yet</td></tr>"
    raw=s.todo.read_text(encoding="utf-8") if s.todo.exists() else ""
    running=s.run is not None and s.run.poll() is None
    body=f"""<!doctype html><meta charset=utf-8><title>ARQUILO Workbench</title>
<style>body{{font:15px system-ui;max-width:1100px;margin:32px auto;padding:0 18px}}textarea,input,select{{font:inherit;width:100%;box-sizing:border-box;padding:8px}}textarea{{min-height:120px}}button{{padding:8px 14px;margin:6px 4px 6px 0}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #ddd;padding:7px;text-align:left}}pre{{white-space:pre-wrap;background:#f5f5f5;padding:12px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}.note{{color:#555}}</style>
<h1>ARQUILO Workbench</h1><p class=note>{html.escape(str(s.workdir))} · {html.escape(str(s.todo))}</p><p>{html.escape(message)}</p>
<h2>Tasks</h2><table><tr><th>ID</th><th>Status</th><th>Task</th></tr>{tasks}</table>
<div class=grid><section><h2>Create a plan</h2><p class=note>One task per line. ARQUILO generates the numbered Markdown syntax.</p><form method=post action="/generate?token={s.token}"><textarea name=ideas></textarea><button>Generate plan</button></form></section>
<section><h2>Edit task file</h2><form method=post action="/save?token={s.token}"><textarea name=plan>{html.escape(raw)}</textarea><button>Save task file</button></form></section></div>
<h2>Run</h2><form method=post action="/run?token={s.token}"><button {'disabled' if running else ''}>Start ARQUILO run</button></form><pre>{html.escape(s.run_output[-12000:])}</pre>
<h2>Ask the project</h2><p class=note>Read-only Codex access to the workdir. This does not create or complete an ARQUILO task.</p><form method=post action="/ask?token={s.token}"><input name=question placeholder="Why was this implemented this way?" required><select name=depth><option>overview</option><option selected>normal</option><option>deep</option></select><button>Ask</button></form><pre>{html.escape(s.ask_answer)}</pre>"""
    return body.encode()

def handler(state:State):
    class H(BaseHTTPRequestHandler):
        def auth(self):
            return parse_qs(urlparse(self.path).query).get("token",[""])[0]==state.token
        def send(self,msg="",code=200):
            data=page(state,msg); self.send_response(code); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if not self.auth(): self.send_error(403); return
            self.send()
        def do_POST(self):
            if not self.auth(): self.send_error(403); return
            n=int(self.headers.get("Content-Length","0")); form=parse_qs(self.rfile.read(n).decode("utf-8"))
            path=urlparse(self.path).path
            try:
                if path=="/generate":
                    state.todo.write_text(generated_plan(form.get("ideas",[""])[0]),encoding="utf-8"); self.send("Plan generated.")
                elif path=="/save":
                    state.todo.write_text(form.get("plan",[""])[0],encoding="utf-8"); self.send("Task file saved.")
                elif path=="/ask":
                    state.ask_answer=ask(workdir=state.workdir,question=form.get("question",[""])[0],depth=form.get("depth",["normal"])[0])["answer"]; self.send()
                elif path=="/run":
                    if state.run is not None and state.run.poll() is None: self.send("A run is already active.",409); return
                    cmd=[sys.executable,"-B",str(Path(__file__).with_name("arquilo.py")),"run","--workdir",str(state.workdir),"--todo-file",str(state.todo),"--process-stop-policy","controller-only"]
                    state.run=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                    def collect():
                        out=state.run.communicate()[0]
                        with state.lock: state.run_output=out
                    threading.Thread(target=collect,daemon=True).start(); self.send("Run started.")
                else:self.send_error(404)
            except Exception as exc:self.send(f"{type(exc).__name__}: {exc}",500)
        def log_message(self,fmt,*args): pass
    return H

def main(argv=None)->int:
    p=argparse.ArgumentParser(description="Start the local ARQUILO browser workbench."); p.add_argument("--workdir",default="."); p.add_argument("--todo-file",default="tasks.md"); p.add_argument("--port",type=int,default=8765); a=p.parse_args(argv)
    work=Path(a.workdir).expanduser().resolve(); todo=Path(a.todo_file).expanduser(); todo=(todo if todo.is_absolute() else work/todo).resolve()
    if not work.is_dir() or not todo.is_relative_to(work): p.error("workdir must exist and todo-file must be inside it")
    token=secrets.token_urlsafe(24); state=State(work,todo,token); server=ThreadingHTTPServer(("127.0.0.1",a.port),handler(state))
    print(f"ARQUILO Workbench: http://127.0.0.1:{a.port}/?token={token}"); print("Bound to loopback only. Ctrl-C to stop.")
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0
if __name__=="__main__":raise SystemExit(main())
