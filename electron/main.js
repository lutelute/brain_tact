// brain_tact Electron シェル — 常駐ダッシュボード(localhost:8787)を表示するだけ。
// 機能はすべて Python core 側。Electron は「窓と tray」だけを担う(引き算)。
const { app, BrowserWindow, Tray, Menu, nativeImage, shell } = require('electron');
const path = require('path');
const http = require('http');
const os = require('os');
const { spawn } = require('child_process');

const PORT = 8787;
const DASH_URL = `http://127.0.0.1:${PORT}`;
const PROJECT = '/Users/shigenoburyuto/Documents/GitHub/tool_dev_SGNB/brain_tact';
const VENV_PY = path.join(os.homedir(), '.venvs/brain_tact/bin/python');

let win = null;
let tray = null;
let sidecar = null;

// ダッシュボードが既に起動しているか
function ping(cb) {
  const req = http.get(`${DASH_URL}/api/state`, (r) => { r.destroy(); cb(true); });
  req.on('error', () => cb(false));
  req.setTimeout(1500, () => { req.destroy(); cb(false); });
}

// launchd 常駐が無いときだけ Python serve をサイドカー起動
function startSidecar() {
  sidecar = spawn(VENV_PY, ['-m', 'brain_tact.cli', 'serve', '--no-browser'], {
    cwd: PROJECT,
    env: { ...process.env, PYTHONPATH: path.join(PROJECT, 'src') },
    stdio: 'ignore',
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 860,
    height: 940,
    minWidth: 520,
    title: 'brain_tact',
    backgroundColor: '#0d0f13',
    icon: path.join(__dirname, 'icon.png'),
    titleBarStyle: 'hiddenInset',
    show: false,
  });
  win.loadURL(DASH_URL);
  win.once('ready-to-show', () => win.show());
  // 閉じる=終了ではなく隠す(tray 常駐)
  win.on('close', (e) => {
    if (!app.isQuitting) { e.preventDefault(); win.hide(); }
  });
}

function createTray() {
  const img = nativeImage
    .createFromPath(path.join(__dirname, 'icon.png'))
    .resize({ width: 18, height: 18 });
  tray = new Tray(img);
  tray.setToolTip('brain_tact — critique-first supervisor');
  tray.on('click', () => (win.isVisible() ? win.hide() : (win.show(), win.focus())));
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'ダッシュボードを開く', click: () => { win.show(); win.focus(); } },
    { label: 'ブラウザで開く', click: () => shell.openExternal(DASH_URL) },
    { label: '再読み込み', click: () => win.reload() },
    { type: 'separator' },
    { label: '終了', click: () => { app.isQuitting = true; app.quit(); } },
  ]));
}

app.whenReady().then(() => {
  ping((up) => {
    if (!up) startSidecar();
    // 常駐済みなら即、サイドカー起動なら立ち上がりを待つ
    setTimeout(() => { createWindow(); createTray(); }, up ? 0 : 1800);
  });
  app.on('activate', () => { if (win) { win.show(); win.focus(); } });
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (sidecar) sidecar.kill();
});
app.on('window-all-closed', () => {}); // tray で常駐し続ける
