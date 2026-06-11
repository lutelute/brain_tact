"""brain ダッシュボード — localhostで全セッションの掃除状況を見える化する。

stdlib http.server のみ(依存追加なし)。
- GET /           : ダッシュボードHTML(自動更新)
- GET /api/state  : 掃除判定込みの状態JSON(Tin/AtelierX等が叩く統合API)
- POST /api/scan  : 今すぐスキャン
- POST /api/act   : 介入(send/approve/resume/resolve) — actuatorガードレール経由

起動: uv run brain-tact serve  (または brain-tact dashboard)
"""

import json
import os
import secrets
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler

from . import LATEST_JSON, PENDING_JSON, STATE_DIR, ensure_dirs

DEFAULT_PORT = 8787
TOKEN_FILE = STATE_DIR / "dashboard-token"


def _get_token() -> str:
    """POST保護用トークン(初回起動時に生成してstate/に保存)。

    127.0.0.1バインドでもブラウザの悪意ページからのfetch(CSRF)は届く。
    カスタムヘッダ X-Brain-Token を必須にするとクロスオリジンPOSTは
    preflightで遮断される(サーバーはOPTIONS/CORSに応えない)。
    ローカルの正当なクライアント(Tin/AtelierX/curl)はこのファイルを読んで付ける。
    """
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    ensure_dirs()
    token = secrets.token_hex(16)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    return token


def _build_state() -> dict:
    """最新スナップショット+掃除判定+保留 をまとめた統合状態。"""
    from .cleanup import summarize
    from .state import load_pending

    if not LATEST_JSON.exists():
        return {"error": "no snapshot yet", "sessions": [], "pending": []}
    snap = json.loads(LATEST_JSON.read_text())
    cl = summarize(snap)
    pending = [i for i in load_pending().get("items", []) if i["status"] == "open"]
    from .cycle import recent_incidents
    return {
        "taken_at": snap.get("taken_at"),
        "totals": snap.get("totals"),
        "headline": cl["headline"],
        "closeable": cl["closeable"],
        "needs_handover": cl["needs_handover"],
        "sessions": cl["sessions"],
        "pending": pending,
        "incidents": recent_incidents(hours=24)[-5:],
    }


# ---------------------------------------------------------------------------
# HTML(自動更新つき・依存なしのバニラJS)
# ---------------------------------------------------------------------------

PAGE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>🎼 brain_tact</title>
<link rel="icon" type="image/png" href="/favicon.png">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,system-ui,sans-serif;
  background:#14161a;color:#e6e8eb}
header{padding:14px 18px;background:#1b1e24;border-bottom:1px solid #2a2e36;
  position:sticky;top:0;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:18px;margin:0}
.headline{color:#9fe6c4;font-weight:600}
.meta{color:#7b8290;font-size:12px;margin-left:auto}
.wrap{padding:18px;max-width:1100px;margin:0 auto}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:760px){.cols{grid-template-columns:1fr}}
.card{background:#1b1e24;border:1px solid #2a2e36;border-radius:10px;
  padding:14px;margin-bottom:16px}
.card h2{font-size:13px;margin:0 0 10px;color:#9aa3b2;letter-spacing:.04em;
  text-transform:uppercase}
.row{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;
  background:#21252c;margin-bottom:7px}
.row:last-child{margin-bottom:0}
.proj{font-weight:600;min-width:120px}
.reason{color:#aeb4bf;font-size:13px;flex:1}
.tty{color:#6b7280;font-size:11px;font-family:ui-monospace,monospace}
.btn{background:#2d6a4f;color:#fff;border:0;border-radius:6px;padding:6px 11px;
  font-size:12px;cursor:pointer}
.btn:hover{background:#358460}
.btn.ghost{background:#343a44}.btn.ghost:hover{background:#3f4651}
.badge{font-size:11px;padding:2px 8px;border-radius:20px;font-weight:600}
.b-closeable{background:#1d4d3a;color:#9fe6c4}
.b-needs_handover{background:#5a4a1d;color:#f0d98a}
.b-needs_user{background:#5a2d2d;color:#f0a0a0}
.b-active{background:#24303f;color:#8fb8e6}
.b-resumable{background:#3a3550;color:#c4b0e6}
.b-ignored{background:#2a2e36;color:#7b8290}
.empty{color:#6b7280;font-style:italic;padding:6px 2px}
.sess{font-size:13px}
.prow{padding:9px 10px;border-radius:8px;background:#21252c;margin-bottom:7px}
.prow-head{display:flex;gap:10px;align-items:baseline;margin-bottom:7px}
.prow-acts{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.note{color:#7b8290;font-size:12px}
.act{font-size:11px;color:#7b8290;margin-top:2px}
button:disabled{opacity:.5;cursor:default}
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);
  background:#2a2e36;border:1px solid #3a4150;padding:10px 16px;border-radius:8px;
  opacity:0;transition:.3s;pointer-events:none}
#toast.show{opacity:1}
#sendbar{display:none;position:fixed;bottom:0;left:0;right:0;z-index:10;
  background:#1d2128;border-top:1px solid #2d6a4f;padding:10px 18px;
  gap:10px;align-items:center}
#sendbar.open{display:flex}
#sb-msg{flex:1;background:#14161a;border:1px solid #343a44;border-radius:6px;
  color:#e6e8eb;padding:7px 10px;font-size:13px}
#sb-msg:focus{outline:1px solid #2d6a4f}
#sb-target{color:#9fe6c4}
</style></head>
<body>
<header>
  <h1><img src="/favicon.png" width="22" style="vertical-align:-4px;border-radius:5px"> brain_tact</h1>
  <span class="headline" id="headline">読み込み中…</span>
  <span class="meta" id="meta"></span>
  <button class="btn ghost" id="rescan" title="今すぐ再スキャン">⟳ スキャン</button>
</header>
<div class="wrap">
  <div class="cols">
    <div class="card">
      <h2>🔬 要改善(完了報告だが粗を探す)</h2>
      <div id="closeable"></div>
    </div>
    <div class="card">
      <h2>⚠️ 満杯(コミットで保全・改善継続)</h2>
      <div id="handover"></div>
    </div>
  </div>
  <div class="card">
    <h2>⏸ ユーザー判断待ち(保留)</h2>
    <div id="pending"></div>
  </div>
  <div class="card">
    <h2>全セッション</h2>
    <div id="all"></div>
  </div>
</div>
<div id="sendbar">
  <span>→ <b id="sb-target"></b></span>
  <input id="sb-msg" placeholder="指示を入力して⏎ (Escで閉じる)">
  <button class="btn" id="sb-send">送信</button>
  <button class="btn ghost" id="sb-close">✕</button>
</div>
<div id="toast"></div>
<script>
const CAT={closeable:'要改善',needs_handover:'満杯',needs_user:'要判断',
  active:'稼働中',resumable:'改善ループ',ignored:'対象外'};
let STATE={sessions:[],pending:[]};
const TOKEN='__BRAIN_TOKEN__';  // 配信時にサーバーが埋める(POST保護用)
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(m){const t=document.getElementById('toast');t.textContent=m;
  t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3500)}
async function act(p){
  toast('送信中…');
  const r=await fetch('/api/act',{method:'POST',
    headers:{'Content-Type':'application/json','X-Brain-Token':TOKEN},
    body:JSON.stringify(p)});
  const j=await r.json();toast(j.result||j.error||'done');setTimeout(refresh,800)}
// 任意指示 — インライン入力バー(Electronはwindow.prompt非対応のため)
let SENDTO=null;
function sendTo(tty,proj){
  SENDTO=tty;
  document.getElementById('sb-target').textContent=proj||tty;
  document.getElementById('sendbar').classList.add('open');
  document.getElementById('sb-msg').focus();
}
function sbClose(){SENDTO=null;
  document.getElementById('sendbar').classList.remove('open');
  document.getElementById('sb-msg').value=''}
function sbSend(){
  const m=document.getElementById('sb-msg').value;
  if(!SENDTO||!m.trim())return;
  act({tool:'act_send',tty:SENDTO,message:m.trim(),reason:'dashboard手動指示'});
  sbClose();
}
document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('sb-send').onclick=sbSend;
  document.getElementById('sb-close').onclick=sbClose;
  document.getElementById('sb-msg').addEventListener('keydown',e=>{
    if(e.key==='Enter')sbSend();
    if(e.key==='Escape')sbClose();
  });
});
// data属性ボタン群(JSONを属性に埋めない=日本語/引用符で壊れない)
function btns(tty,proj,cat){
  const CRIT="自分のプロジェクトを批判的に自己レビューし(完了と思っても必ず粗・改善余地を探す)、最も価値の高い改善を1つ実行して、改善ループを続けてください。閉じないこと。";
  if(cat==='ignored')return '';
  let b=`<button class="btn" data-do="send" data-tty="${tty}" data-proj="${esc(proj||'')}">💬指示</button>`;
  if(cat!=='active')
    b+=`<button class="btn" data-do="send" data-tty="${tty}" data-proj="${esc(proj||'')}" data-msg="${CRIT}">🔬改善</button>`;
  if(cat==='needs_user')
    b+=`<button class="btn ghost" data-do="approve" data-tty="${tty}" data-opt="1">✓承認1</button>`+
       `<button class="btn ghost" data-do="approve" data-tty="${tty}" data-opt="2">2</button>`;
  if(cat==='needs_handover')
    b+=`<button class="btn ghost" data-do="send" data-tty="${tty}" data-proj="${esc(proj||'')}" data-msg="未コミットの変更をコミットして成果を保全してから、批判的に次の改善を続けてください。閉じないこと。">💾保全</button>`;
  return b}
function render(d){
  STATE=d;
  document.getElementById('headline').textContent=d.headline||'';
  document.getElementById('meta').textContent=
    ((d.incidents||[]).length?'⚠️障害'+d.incidents.length+'  ':'')+
    (d.taken_at||'').replace('T',' ').slice(0,16)+
    (d.totals&&d.totals.usage&&d.totals.usage.pct!=null?'  枠'+d.totals.usage.pct.toFixed(0)+'%':'');
  document.getElementById('meta').title=(d.incidents||[]).map(i=>i.ts+' '+i.error).join('\\n');

  const sByTty=Object.fromEntries(d.sessions.map(s=>[s.tty,s]));
  const cl=document.getElementById('closeable');
  cl.innerHTML=d.closeable.length?d.closeable.map(x=>
    `<div class="row"><span class="proj">${esc(x.project||'-')}</span>
     <span class="reason">${esc(x.reason)}</span>
     <span class="tty">${esc(x.tty)}</span>
     <button class="btn" data-do="send" data-tty="${x.tty}" data-proj="${esc(x.project||'')}">💬指示</button></div>`
  ).join(''):'<div class="empty">なし</div>';

  const ho=document.getElementById('handover');
  ho.innerHTML=d.needs_handover.length?d.needs_handover.map(x=>
    `<div class="row"><span class="proj">${esc(x.project||'-')}</span>
     <span class="reason">${esc(x.reason)}</span>
     <button class="btn" data-do="send" data-tty="${x.tty}" data-proj="${esc(x.project||'')}" data-msg="未コミットの変更をコミットして成果を保全してから、批判的に次の改善を続けてください。閉じないこと。">💾保全</button>
     <button class="btn ghost" data-do="send" data-tty="${x.tty}" data-proj="${esc(x.project||'')}">💬指示</button></div>`
  ).join(''):'<div class="empty">なし</div>';

  const pe=document.getElementById('pending');
  pe.innerHTML=d.pending.length?d.pending.map((p,pi)=>{
    // 脳のsuggested_actionでtool/argsが揃ったものだけ実行ボタン化(noteのみは説明表示)
    const acts=(p.suggested_actions||[]).map((sa,si)=>sa.tool&&sa.args
      ? `<button class="btn" data-do="sa" data-pi="${pi}" data-si="${si}">${esc(sa.label||sa.tool)}</button>`
      : `<span class="note">・${esc(sa.label||sa.note||'')}</span>`).join(' ');
    return `<div class="prow"><div class="prow-head">
      <span class="proj">${esc(p.project||p.tty)}</span>
      <span class="reason">${esc(p.summary)}</span></div>
      <div class="prow-acts">${acts}
      <button class="btn" data-do="send" data-tty="${p.tty}" data-proj="${esc(p.project||'')}">💬指示</button>
      <button class="btn ghost" data-do="resolve" data-pid="${p.id}">✓解決</button></div></div>`
  }).join(''):'<div class="empty">保留なし 🎉</div>';

  const all=document.getElementById('all');
  all.innerHTML=d.sessions.map(s=>{
    const c=s.cleanup.category;
    return `<div class="row sess"><span class="badge b-${c}">${CAT[c]||c}</span>
      <span class="proj">${esc(s.project||'-')}</span>
      <div style="flex:1"><div>${esc(s.cleanup.reason)}</div>
      <div class="act">${esc(s.cleanup.action)}</div></div>
      ${btns(s.tty,s.project,c)}
      <span class="tty">${esc(s.tty)}</span></div>`}).join('');
}
// イベント委譲(全ボタンを1リスナーで処理)
document.addEventListener('click',e=>{
  const b=e.target.closest('[data-do]');if(!b)return;
  const d=b.dataset;
  if(d.do==='send'){
    if(d.msg) act({tool:'act_send',tty:d.tty,message:d.msg,reason:'dashboard'});
    else sendTo(d.tty,d.proj);
  }else if(d.do==='approve'){
    act({tool:'act_approve',tty:d.tty,option:d.opt,reason:'dashboard承認'});
  }else if(d.do==='resolve'){
    act({tool:'resolve_pending',item_id:d.pid,resolution:'dashboardで解決'});
  }else if(d.do==='sa'){
    const p=STATE.pending[+d.pi],sa=p.suggested_actions[+d.si];
    act({...sa.args,tool:sa.tool,reason:'dashboard:'+(sa.label||sa.tool),_resolve:p.id});
  }
});
// 再スキャン(POST /api/scan → latest.json更新 → SSEが自動で再描画)
document.getElementById('rescan').onclick=async()=>{
  toast('スキャン中…');
  try{
    await fetch('/api/scan',{method:'POST',
      headers:{'X-Brain-Token':TOKEN},body:'{}'});
    toast('スキャン完了');
  }catch(_){toast('スキャン失敗')}
};
// act 後の即時反映用(pending解決などは latest.json mtime を変えないため)
async function refresh(){try{render(await (await fetch('/api/state')).json())}catch(_){}}
// ポーリング廃止 → SSE。接続時に現在状態が即届き、以降は変化時のみ push される
const _es=new EventSource('/events');
_es.onmessage=e=>{try{render(JSON.parse(e.data))}catch(_){}};
_es.onerror=()=>{};  // EventSource は自動再接続する
</script>
</body></html>"""


# ---------------------------------------------------------------------------
# ミニ監視窓(/mini) — 常時視界に置ける簡易窓。Electronが最前面小窓で表示する
# ---------------------------------------------------------------------------

MINI_PAGE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>brain_tact mini</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:12px/1.45 -apple-system,system-ui,sans-serif;
  background:#14161a;color:#e6e8eb;overflow:hidden;height:100vh;
  display:flex;flex-direction:column}
header{padding:7px 10px;background:#1b1e24;border-bottom:1px solid #2a2e36;
  display:flex;align-items:center;gap:8px;-webkit-app-region:drag;
  user-select:none;flex-shrink:0}
.hl{font-weight:600;color:#9fe6c4;font-size:11px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;flex:1}
.t{color:#7b8290;font-size:10px}
.x{-webkit-app-region:no-drag;cursor:pointer;color:#7b8290;border:0;
  background:none;font-size:13px;padding:0 2px}
.x:hover{color:#e6e8eb}
.list{overflow-y:auto;flex:1;padding:5px}
.row{display:flex;gap:7px;padding:4px 7px;border-radius:6px;margin-bottom:3px;
  background:#1b1e24;align-items:center;cursor:pointer}
.row:hover{background:#22262e}
.row.sel{outline:1px solid #2d6a4f;background:#1d2a24}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.d-needs_user{background:#f0a0a0}
.d-needs_handover{background:#f0d98a}
.d-closeable{background:#9fe6c4}
.d-resumable{background:#c4b0e6}
.d-active{background:#8fb8e6}
.d-ignored{background:#4a4f58}
.proj{font-weight:600;white-space:nowrap;max-width:42%;overflow:hidden;
  text-overflow:ellipsis;flex-shrink:0}
.why{color:#8b919c;font-size:11px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;flex:1}
.empty{color:#6b7280;font-style:italic;padding:8px}
footer{padding:6px 10px;background:#1b1e24;border-top:1px solid #2a2e36;
  display:flex;align-items:center;gap:10px;flex-shrink:0;font-size:11px}
.pend{color:#f0a0a0;font-weight:600}
.spacer{flex:1}
.btn{background:#343a44;color:#e6e8eb;border:0;border-radius:5px;
  padding:3px 8px;font-size:11px;cursor:pointer}
.btn:hover{background:#3f4651}
.btn.go{background:#2d6a4f}.btn.go:hover{background:#358460}
a{color:#8fb8e6;text-decoration:none;font-size:11px}
#bar{display:none;flex-direction:column;gap:5px;padding:7px 10px;
  background:#1d2128;border-top:1px solid #2d6a4f;flex-shrink:0}
.bar-head{display:flex;align-items:center;gap:6px;font-size:11px}
.bar-head b{color:#9fe6c4}
.bar-row{display:flex;gap:5px}
#bmsg{flex:1;background:#14161a;border:1px solid #343a44;border-radius:5px;
  color:#e6e8eb;padding:4px 7px;font-size:12px}
#bmsg:focus{outline:1px solid #2d6a4f}
#toast{position:fixed;bottom:64px;left:50%;transform:translateX(-50%);
  background:#2a2e36;border:1px solid #3a4150;padding:5px 12px;border-radius:6px;
  font-size:11px;opacity:0;transition:.3s;pointer-events:none;max-width:90%;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#toast.show{opacity:1}
</style></head>
<body>
<header>
  <span class="hl" id="hl">接続中…</span>
  <span class="t" id="t"></span>
  <button class="x" onclick="window.close()" title="隠す">✕</button>
</header>
<div class="list" id="list"></div>
<div id="bar">
  <div class="bar-head">→ <b id="btarget"></b>
    <span class="spacer"></span>
    <button class="x" id="bclose" title="閉じる">✕</button></div>
  <div class="bar-row">
    <input id="bmsg" placeholder="指示を入力して⏎">
    <button class="btn go" id="bsend">送信</button>
  </div>
  <div class="bar-row">
    <button class="btn" id="bcrit" title="批判的改善ループの定型指示">🔬 改善</button>
    <button class="btn" id="bsave" title="コミットで保全の定型指示">💾 保全</button>
    <button class="btn" id="bok" style="display:none" title="承認プロンプトに1">✓ 承認1</button>
  </div>
</div>
<div id="toast"></div>
<footer>
  <span class="pend" id="pend"></span>
  <span class="spacer"></span>
  <button class="btn" id="rescan" title="今すぐ再スキャン(データ更新)">⟳</button>
  <button class="btn" id="reload" title="UIを再読み込み(SSE再接続・表示回復)">↻ UI</button>
  <a href="/" target="_blank" title="フルダッシュボード">⤢ フル</a>
</footer>
<script>
const TOKEN='__BRAIN_TOKEN__';
const ORDER={needs_user:0,needs_handover:1,closeable:2,resumable:3,active:4,ignored:5};
const CRIT="自分のプロジェクトを批判的に自己レビューし(完了と思っても必ず粗・改善余地を探す)、最も価値の高い改善を1つ実行して、改善ループを続けてください。改善は検証可能に(テスト・実行確認を通し、論理単位でコミットして締める)。閉じないこと。";
const SAVE="未コミットの変更をコミットして成果を保全してから、批判的に次の改善を続けてください。閉じないこと。";
let SEL=null;  // {tty, proj, cat}
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(m){const t=document.getElementById('toast');t.textContent=m;
  t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3500)}
function render(d){
  const inc=(d.incidents||[]).length;
  document.getElementById('hl').textContent=(inc?`⚠️${inc} `:'')+(d.headline||'');
  document.getElementById('hl').title=(d.incidents||[]).map(i=>i.ts+' '+i.error).join('\\n');
  document.getElementById('t').textContent=(d.taken_at||'').slice(11,16);
  const ss=(d.sessions||[]).slice().sort((a,b)=>
    (ORDER[a.cleanup.category]??9)-(ORDER[b.cleanup.category]??9));
  document.getElementById('list').innerHTML=ss.map(s=>
    `<div class="row${SEL&&SEL.tty===s.tty?' sel':''}" data-tty="${s.tty}"
      data-proj="${esc(s.project||'')}" data-cat="${s.cleanup.category}"
      title="${esc(s.tty+' '+s.state_hint+' — '+s.cleanup.reason)}">
     <span class="dot d-${s.cleanup.category}"></span>
     <span class="proj">${esc(s.project||'-')}</span>
     <span class="why">${esc(s.cleanup.reason)}</span></div>`).join('')
    ||'<div class="empty">セッションなし</div>';
  const n=(d.pending||[]).length;
  document.getElementById('pend').textContent=n?`⏸ 保留${n}`:'';
  // 選択していたセッションが消えたらバーを閉じる
  if(SEL&&!ss.some(s=>s.tty===SEL.tty))closeBar();
}
new EventSource('/events').onmessage=e=>{try{render(JSON.parse(e.data))}catch(_){}};
// --- 行選択 → 操作バー(Electronはwindow.prompt非対応のためインライン入力) ---
const bar=document.getElementById('bar'),bmsg=document.getElementById('bmsg');
function openBar(sel){
  SEL=sel;
  document.getElementById('btarget').textContent=sel.proj||sel.tty;
  document.getElementById('bok').style.display=
    sel.cat==='needs_user'?'':'none';
  bar.style.display='flex';
  document.querySelectorAll('.row').forEach(r=>
    r.classList.toggle('sel',r.dataset.tty===sel.tty));
  bmsg.focus();
}
function closeBar(){SEL=null;bar.style.display='none';bmsg.value='';
  document.querySelectorAll('.row.sel').forEach(r=>r.classList.remove('sel'))}
document.getElementById('list').addEventListener('click',e=>{
  const r=e.target.closest('.row');if(!r||!r.dataset.tty)return;
  if(r.dataset.cat==='ignored'){toast('claude未起動(対象外)');return}
  if(SEL&&SEL.tty===r.dataset.tty){closeBar();return}
  openBar({tty:r.dataset.tty,proj:r.dataset.proj,cat:r.dataset.cat});
});
document.getElementById('bclose').onclick=closeBar;
async function act(p){
  toast('送信中…');
  try{
    const r=await fetch('/api/act',{method:'POST',
      headers:{'Content-Type':'application/json','X-Brain-Token':TOKEN},
      body:JSON.stringify(p)});
    const j=await r.json();toast(j.result||j.error||'done');
  }catch(_){toast('通信エラー')}
}
function sendMsg(text){
  if(!SEL||!text.trim())return;
  act({tool:'act_send',tty:SEL.tty,message:text.trim(),reason:'ミニ監視から手動指示'});
  bmsg.value='';
}
document.getElementById('bsend').onclick=()=>sendMsg(bmsg.value);
bmsg.addEventListener('keydown',e=>{if(e.key==='Enter')sendMsg(bmsg.value);
  if(e.key==='Escape')closeBar()});
document.getElementById('bcrit').onclick=()=>sendMsg(CRIT);
document.getElementById('bsave').onclick=()=>sendMsg(SAVE);
document.getElementById('bok').onclick=()=>{if(SEL)
  act({tool:'act_approve',tty:SEL.tty,option:'1',reason:'ミニ監視から手動承認'})};
function rescan(){fetch('/api/scan',{method:'POST',
  headers:{'X-Brain-Token':TOKEN},body:'{}'}).catch(()=>{})}
document.getElementById('rescan').onclick=rescan;
document.getElementById('reload').onclick=()=>location.reload();
// 表示中のみ90秒ごとに自動再スキャン(巡回4回/日の隙間を「いま」で埋める)
setInterval(()=>{if(!document.hidden)rescan()},90000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)rescan()});
rescan();  // 開いた時・↻UI直後も最新に
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静かに
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self) -> bool:
        """DNS rebinding対策: Hostがlocalhost系以外なら拒否する。"""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            self._send(403, json.dumps({"error": "bad host"}))
            return
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE.replace("__BRAIN_TOKEN__", _get_token()),
                       "text/html")
        elif self.path.startswith("/mini"):
            self._send(200, MINI_PAGE.replace("__BRAIN_TOKEN__", _get_token()),
                       "text/html")
        elif self.path.startswith("/api/state"):
            self._send(200, json.dumps(_build_state(), ensure_ascii=False))
        elif self.path.startswith("/events"):
            self._sse()
        elif self.path.startswith("/favicon"):
            from . import BRAIN_DIR
            p = BRAIN_DIR / "assets" / "favicon.png"
            if p.exists():
                self._send(200, p.read_bytes(), "image/png")
            else:
                self._send(404, b"")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def _sse(self):
        """Server-Sent Events: latest.json / pending.json が変化した時だけpushする。

        クライアント側のポーリング(15秒ごとの fetch)を廃止し、1本の接続を
        保持して変化時のみ更新する。サーバー内は2秒ごとに mtime を stat する
        だけ(軽量)で、重い _build_state は変化時しか呼ばない。
        pending.json も監視対象 — /brain やCLIで保留を解決した場合は
        latest.json が動かないため、片方だけ見ていると画面が古いままになる。
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def watch_key() -> tuple:
            return tuple(
                f.stat().st_mtime if f.exists() else 0.0
                for f in (LATEST_JSON, PENDING_JSON)
            )

        last_key = None
        try:
            while True:
                key = watch_key()
                if key != last_key:
                    last_key = key
                    payload = json.dumps(_build_state(), ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                else:
                    self.wfile.write(b": keepalive\n\n")  # 接続維持コメント
                self.wfile.flush()
                time.sleep(2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return  # クライアント切断

    def do_POST(self):  # noqa: N802
        if not self._host_ok():
            self._send(403, json.dumps({"error": "bad host"}))
            return
        # CSRF対策: ブラウザのクロスオリジンfetchはカスタムヘッダを付けられない
        # (preflightされ、CORS非対応の本サーバーでは必ず失敗する)
        if self.headers.get("X-Brain-Token") != _get_token():
            self._send(403, json.dumps(
                {"error": "X-Brain-Token required (state/dashboard-token)"}))
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send(400, json.dumps({"error": "bad json"}))
            return

        if self.path.startswith("/api/scan"):
            from .scan import run_scan
            run_scan(quick=True)
            self._send(200, json.dumps({"result": "scanned"}))
        elif self.path.startswith("/api/act"):
            self._send(200, json.dumps(self._do_act(payload), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def _do_act(self, p: dict) -> dict:
        """actuator関数をガードレール込みで実行する。"""
        os.environ.setdefault("BRAIN_CYCLE_ID", "dashboard")
        from . import actuator
        tool = p.pop("tool", "")
        resolve_after = p.pop("_resolve", None)
        # ダッシュボードからの操作はreasonを補う(脳のsuggested_actionsはreason欠落あり)
        if tool in ("act_send", "act_approve", "act_resume"):
            p.setdefault("reason", "ダッシュボード操作")
        # ダッシュボードは人間操作なので manual=True(クールダウン・回数制限なし)
        fn = {
            "act_send": lambda **kw: actuator.send_impl(**kw, manual=True),
            "act_approve": lambda **kw: actuator.approve_impl(**kw, manual=True),
            "act_resume": lambda **kw: actuator.resume_impl(**kw, manual=True),
            "resolve_pending": actuator.resolve_pending,
        }.get(tool)
        if fn is None:
            return {"error": f"unknown tool: {tool}"}
        try:
            result = fn(**p)
        except TypeError as e:
            return {"error": f"引数エラー: {e}"}
        # 介入が成功したら紐づく保留も解決
        if resolve_after and (result.startswith("✅") or result.startswith("🧪")):
            from .state import resolve_pending
            resolve_pending(resolve_after, f"dashboardで{tool}実行")
        return {"result": result}


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    server = _ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"🧠 brain dashboard → {url}  (Ctrl-C で停止)")
    if open_browser:
        threading.Timer(0.8, lambda: __import__("webbrowser").open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました")
        server.shutdown()
