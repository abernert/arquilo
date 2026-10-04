# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Static UI only; untrusted text is never inserted as HTML or script."""
HTML = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ARQUILO Workbench</title><link rel="stylesheet" href="/style.css"><script src="/app.js" defer></script></head><body>
<header><h1>ARQUILO <span>Workbench</span></h1><p>Reviewed work and read-only project questions</p></header>
<p id="notice" role="status" aria-live="polite">Connecting…</p>
<section><h2>Saved plan</h2><p id="conflict"></p><table><thead><tr><th>Task</th><th>Status in file</th><th>Title</th></tr></thead><tbody id="tasks"></tbody></table><p class="note">Status text is not by itself independent review evidence.</p></section>
<section><h2>Plan editor</h2><p>Generate a draft, review the diff, then save. New tasks append; existing tasks are never silently replaced.</p><label>New tasks, one per line<textarea id="ideas" rows="3"></textarea></label><button id="generate">Append to draft</button><label>Markdown draft<textarea id="plan" rows="12" spellcheck="false"></textarea></label><button id="preview">Validate and preview</button><button id="save" disabled>Save reviewed draft</button><button id="reload">Discard draft and reload</button><pre id="diff"></pre></section>
<section><h2>Run control <span id="runStatus">idle</span></h2><div class="grid"><label>Call-count limit (0 = unlimited)<input id="limit" type="number" min="0" value="0"></label><label>Model override (optional)<input id="model" autocomplete="off"></label></div><label class="check"><input id="provider" type="checkbox">I approve model usage and trust my Codex provider/configuration. Project contents may leave this computer.</label><label class="check"><input id="adopt" type="checkbox">I reviewed the saved owner edits and explicitly approve adopting them for this run.</label><button id="start">Start / continue saved plan</button><button id="pause" disabled>Pause at next task boundary</button><button id="cancel" disabled>Cancel run</button><p id="runDetail"></p><pre id="output" aria-label="Live run output"></pre></section>
<section><h2>Ask the project <span id="askStatus">idle</span></h2><p>Controlled text excerpts, no direct project tool access. Source anchors are verified; semantic correctness still requires judgement.</p><label>Question<textarea id="question" rows="3"></textarea></label><label>Research depth<select id="depth"><option>overview</option><option selected>normal</option><option>deep</option></select></label><label>Optional relative text-file paths, one per line<textarea id="files" rows="2"></textarea></label><label class="check"><input id="askProvider" type="checkbox">I approve sending selected evidence and trust the configured Codex host/provider.</label><button id="ask">Ask</button><button id="askCancel" disabled>Cancel question</button><pre id="answer"></pre><pre id="sources"></pre></section>
<footer>Local-only interface · Browser refresh preserves the server job, not an unsaved draft · Archives stay private</footer></body></html>'''
CSS = '''body{font:16px/1.5 system-ui,sans-serif;margin:auto;padding:24px;max-width:1120px;color:#203044;background:#f5f7fa}header{border-bottom:3px solid #295f85}h1 span{font-weight:400}h2{font-size:1.25rem}section{background:white;border:1px solid #d9e0e6;border-radius:8px;padding:20px;margin:20px 0}textarea,input,select,button{font:inherit;box-sizing:border-box}textarea,input,select{width:100%;padding:8px;border:1px solid #b0beca;border-radius:4px}textarea{font-family:ui-monospace,monospace}label{display:block;margin:10px 0}.check{display:flex;align-items:flex-start;gap:10px}.check input{width:auto;margin-top:6px}button{padding:9px 14px;margin:6px 6px 6px 0;border:1px solid #295f85;border-radius:4px;background:#eef4f9;cursor:pointer}button:disabled{opacity:.45;cursor:default}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f8;padding:12px;max-height:420px;overflow:auto}table{border-collapse:collapse;width:100%}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd;overflow-wrap:anywhere}.note,footer{font-size:.88rem;color:#526578}#notice,#conflict{color:#9d390b}h2 span{font-size:.85rem;padding:4px 8px;background:#edf1f5;border-radius:4px}@media(max-width:680px){body{padding:10px}.grid{display:block}section{padding:12px}table{font-size:.85rem}}'''
JS = r'''"use strict";
const el = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
if(fragment.has('token')) {sessionStorage.setItem('arquilo-token',fragment.get('token'));history.replaceState(null,'','/');}
const token = sessionStorage.getItem('arquilo-token') || '';
let revision=null,dirty=false,validated=null,current=null,runRequest=null,askRequest=null;
function uuid(){return crypto.randomUUID().replaceAll('-','');}
function notice(text){el('notice').textContent=text;}
async function api(path,data){
 const options={headers:{Authorization:'Bearer '+token},cache:'no-store'};
 if(data!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data);}
 const response=await fetch(path,options), result=await response.json();
 if(!response.ok)throw new Error(result.error || 'Request rejected');
 return result;
}
function editorChanged(){dirty=true;validated=null;runRequest=null;el('save').disabled=true;}
el('plan').addEventListener('input',editorChanged);
async function refresh(){
 try{
  const next=await api('/api/state');if(current&&next.sequence<=current.sequence)return;current=next;const p=current.plan;
  if(revision===null){el('plan').value=p.text;revision=p.revision;}
  else if(revision!==p.revision&&!dirty){el('adopt').checked=false;el('plan').value=p.text;revision=p.revision;validated=null;}
  el('conflict').textContent=(dirty&&revision!==p.revision)?'The saved plan changed. Your draft is preserved; compare it before reloading.':'';
  el('tasks').replaceChildren();
  for(const task of p.tasks){const row=document.createElement('tr');for(const text of [task.id,task.status,task.title]){const cell=document.createElement('td');cell.textContent=text;row.append(cell);}el('tasks').append(row);}
  const run=current.run,ask=current.ask;
  el('runStatus').textContent=run.status;el('askStatus').textContent=ask.status;
  el('output').textContent=run.output||'';
  const control=(run.worker||{}).controller||{};
  el('runDetail').textContent=run.stop_marker||run.warning||('Controller: '+(control.status||'not started')+'; exit: '+(run.exit_code??'pending')+'; reviewed this run: '+(control.reviewed_task_ids||[]).join(', '));
  for(const id of ['plan','ideas','preview','generate'])el(id).disabled=run.active;
  el('save').disabled=run.active||!validated||validated.text!==el('plan').value||validated.revision!==revision||revision!==p.revision;
  el('start').disabled=run.active||dirty;el('pause').disabled=!run.active||run.status==='pausing'||run.status==='cancelling';el('cancel').disabled=!run.active||run.status==='cancelling';
  el('ask').disabled=ask.active;el('askCancel').disabled=!ask.active;
  if(ask.answer){el('answer').textContent=ask.answer.answer;el('sources').textContent=JSON.stringify({citations:ask.answer.citations,limitations:ask.answer.limitations,changed_sources:ask.answer.changed_sources},null,2);}
  else if(ask.active)el('answer').textContent=((ask.worker||{}).progress||{}).message||'Question running…';
  else if(ask.status==='cancelled'){el('answer').textContent='Question cancelled; no final answer accepted.';el('sources').textContent='';}
  else if(ask.status==='failed')el('answer').textContent='Question failed. No answer was accepted. Inspect the private job/Ask archives.';
 }catch(error){notice(error.message);}
}
function button(id,fn){el(id).addEventListener('click',async()=>{try{await fn();await refresh();}catch(error){notice(error.message);}});}
button('generate',async()=>{const p=await api('/api/plan/generate',{ideas:el('ideas').value,base:el('plan').value,revision});el('plan').value=p.text;editorChanged();el('diff').textContent=p.diff;notice('Draft appended. Validate and review before saving.');});
button('preview',async()=>{const text=el('plan').value;const p=await api('/api/plan/preview',{text,revision});el('diff').textContent=p.issues.length?JSON.stringify(p.issues,null,2):p.diff||'No changes';validated=p.valid?{text,revision}:null;notice(p.valid?'Valid. Review the diff, then save.':'Validation failed; nothing was saved.');});
button('save',async()=>{if(!validated||validated.text!==el('plan').value)throw new Error('Preview this draft first');const p=await api('/api/plan/save',{text:el('plan').value,revision});revision=p.revision;el('plan').value=p.text;dirty=false;validated=null;el('adopt').checked=false;notice('Saved with backup. Controller adoption is not automatic.');});
button('reload',async()=>{if(dirty&&!confirm('Discard the unsaved draft?'))return;const p=(await api('/api/state')).plan;revision=p.revision;el('plan').value=p.text;dirty=false;validated=null;notice('Saved plan loaded.');});
for(const id of ['limit','model','provider','adopt'])el(id).addEventListener('change',()=>{runRequest=null;});
button('start',async()=>{if(!el('provider').checked)throw new Error('Confirm provider/configuration consent');if(!runRequest)runRequest={request_id:uuid(),revision:current.plan.revision,allow_provider:true,adopt_plan:el('adopt').checked,max_calls:Number(el('limit').value),model:el('model').value||null};await api('/api/run/start',runRequest);runRequest=null;el('adopt').checked=false;notice('Run accepted. Pause waits for a safe boundary; cancellation retains a stop marker.');});
button('pause',async()=>{await api('/api/run/pause',{id:current.run.id});notice('Pause requested; current work and review finish first.');});
button('cancel',async()=>{if(confirm('Cancel this run? Partial work and process_stop will be retained.'))await api('/api/run/cancel',{id:current.run.id});});
for(const id of ['question','depth','files','askProvider'])el(id).addEventListener('input',()=>{askRequest=null;});
button('ask',async()=>{if(!el('askProvider').checked)throw new Error('Confirm evidence/provider consent');if(!askRequest)askRequest={request_id:uuid(),question:el('question').value,depth:el('depth').value,allow_provider:true,files:el('files').value.split('\n').map(x=>x.trim()).filter(Boolean)};await api('/api/ask/start',askRequest);askRequest=null;el('answer').textContent='Question queued…';el('sources').textContent='';notice('Question started separately from task execution.');});
button('askCancel',()=>api('/api/ask/cancel',{id:current.ask.id}));
async function poll(){await refresh();setTimeout(poll,1000);}notice('Local session connected. No model call starts without an explicit action.');poll();
'''
