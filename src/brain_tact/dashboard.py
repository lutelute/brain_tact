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
import socketserver
import threading
from http.server import BaseHTTPRequestHandler

from . import LATEST_JSON

DEFAULT_PORT = 8787


def _build_state() -> dict:
    """最新スナップショット+掃除判定+保留 をまとめた統合状態。"""
    from .cleanup import summarize
    from .state import load_pending

    if not LATEST_JSON.exists():
        return {"error": "no snapshot yet", "sessions": [], "pending": []}
    snap = json.loads(LATEST_JSON.read_text())
    cl = summarize(snap)
    pending = [i for i in load_pending().get("items", []) if i["status"] == "open"]
    return {
        "taken_at": snap.get("taken_at"),
        "totals": snap.get("totals"),
        "headline": cl["headline"],
        "closeable": cl["closeable"],
        "needs_handover": cl["needs_handover"],
        "sessions": cl["sessions"],
        "pending": pending,
    }


# ---------------------------------------------------------------------------
# HTML(自動更新つき・依存なしのバニラJS)
# ---------------------------------------------------------------------------

PAGE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>🧠 brain</title>
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
</style></head>
<body>
<header>
  <h1>🧠 brain</h1>
  <span class="headline" id="headline">読み込み中…</span>
  <span class="meta" id="meta"></span>
</header>
<div class="wrap">
  <div class="cols">
    <div class="card">
      <h2>🧹 閉じてOK</h2>
      <div id="closeable"></div>
    </div>
    <div class="card">
      <h2>💾 要引き継ぎ(閉じる前に保存)</h2>
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
<div id="toast"></div>
<script>
const CAT={closeable:'閉じてOK',needs_handover:'要引き継ぎ',needs_user:'要判断',
  active:'稼働中',resumable:'再開可'};
let STATE={sessions:[],pending:[]};
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(m){const t=document.getElementById('toast');t.textContent=m;
  t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3500)}
async function act(p){
  toast('送信中…');
  const r=await fetch('/api/act',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(p)});
  const j=await r.json();toast(j.result||j.error||'done');setTimeout(load,800)}
// 任意指示(prompt入力)
function sendTo(tty,proj){
  const m=prompt('「'+(proj||tty)+'」に送る指示を入力:','');
  if(m===null||m.trim()==='')return;
  act({tool:'act_send',tty:tty,message:m.trim(),reason:'dashboard手動指示'})}
// data属性ボタン群(JSONを属性に埋めない=日本語/引用符で壊れない)
function btns(tty,proj,cat){
  let b=`<button class="btn" data-do="send" data-tty="${tty}" data-proj="${esc(proj||'')}">💬指示</button>`;
  if(cat==='needs_user')
    b+=`<button class="btn" data-do="approve" data-tty="${tty}" data-opt="1">✓承認1</button>`+
       `<button class="btn ghost" data-do="approve" data-tty="${tty}" data-opt="2">2</button>`;
  if(cat==='needs_handover')
    b+=`<button class="btn" data-do="send" data-tty="${tty}" data-proj="${esc(proj||'')}" data-msg="/引き継ぎ">💾引き継ぎ</button>`;
  if(cat==='resumable')
    b+=`<button class="btn" data-do="send" data-tty="${tty}" data-proj="${esc(proj||'')}" data-msg="進捗を3行で要約し、残作業があれば続行してください">▶続行</button>`;
  return b}
async function load(){
  let d;try{d=await (await fetch('/api/state')).json()}catch(e){return}
  STATE=d;
  document.getElementById('headline').textContent=d.headline||'';
  document.getElementById('meta').textContent=
    (d.taken_at||'').replace('T',' ').slice(0,16)+
    (d.totals&&d.totals.usage&&d.totals.usage.pct!=null?'  枠'+d.totals.usage.pct.toFixed(0)+'%':'');

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
     <button class="btn" data-do="send" data-tty="${x.tty}" data-proj="${esc(x.project||'')}" data-msg="/引き継ぎ">💾引き継ぎ</button>
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
load();setInterval(load,15000);
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

    def do_GET(self):  # noqa: N802
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE, "text/html")
        elif self.path.startswith("/api/state"):
            self._send(200, json.dumps(_build_state(), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):  # noqa: N802
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
