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
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function toast(m){const t=document.getElementById('toast');t.textContent=m;
  t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2500)}
async function act(p){
  const r=await fetch('/api/act',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(p)});
  const j=await r.json();toast(j.result||j.error||'done');load()}
function briefRow(x,btns){
  return `<div class="row"><span class="proj">${esc(x.project||'-')}</span>
    <span class="reason">${esc(x.reason)}</span>
    <span class="tty">${esc(x.tty)}</span>${btns||''}</div>`}
async function load(){
  let d;try{d=await (await fetch('/api/state')).json()}catch(e){return}
  document.getElementById('headline').textContent=d.headline||'';
  document.getElementById('meta').textContent=
    (d.taken_at||'').replace('T',' ').slice(0,16)+
    (d.totals&&d.totals.usage&&d.totals.usage.pct!=null?'  枠'+d.totals.usage.pct.toFixed(0)+'%':'');

  const cl=document.getElementById('closeable');
  cl.innerHTML=d.closeable.length?d.closeable.map(x=>briefRow(x)).join(''):
    '<div class="empty">なし</div>';

  const ho=document.getElementById('handover');
  ho.innerHTML=d.needs_handover.length?d.needs_handover.map(x=>briefRow(x,
    `<button class="btn" onclick='act({tool:"act_send",tty:"${x.tty}",
      message:"作業を引き継ぎ保存してください。要点を3行で残してから止めてOKです",
      reason:"dashboard: 引き継ぎ促し"})'>引き継ぎ依頼</button>`
  )).join(''):'<div class="empty">なし</div>';

  const pe=document.getElementById('pending');
  pe.innerHTML=d.pending.length?d.pending.map(p=>{
    const acts=(p.suggested_actions||[]).slice(0,3).map(sa=>
      `<button class="btn" onclick='act(${JSON.stringify({...sa.args,tool:sa.tool,
        reason:"dashboard:"+(sa.label||sa.tool),_resolve:p.id})})'>${esc(sa.label||sa.tool)}</button>`).join('');
    return `<div class="row"><span class="proj">${esc(p.project||p.tty)}</span>
      <span class="reason">${esc(p.summary)}</span>${acts}
      <button class="btn ghost" onclick='act({tool:"resolve_pending",item_id:"${p.id}",
        resolution:"dashboardで解決"})'>✓解決</button></div>`}).join(''):
    '<div class="empty">保留なし 🎉</div>';

  const all=document.getElementById('all');
  all.innerHTML=d.sessions.map(s=>{
    const c=s.cleanup.category;
    return `<div class="row sess"><span class="badge b-${c}">${CAT[c]||c}</span>
      <span class="proj">${esc(s.project||'-')}</span>
      <div style="flex:1"><div>${esc(s.cleanup.reason)}</div>
      <div class="act">${esc(s.cleanup.action)}</div></div>
      <span class="tty">${esc(s.tty)}</span></div>`}).join('');
}
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
        fn = {
            "act_send": actuator.act_send,
            "act_approve": actuator.act_approve,
            "act_resume": actuator.act_resume,
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
