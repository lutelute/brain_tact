// brain_tact Electron シェル — 常駐ダッシュボード(localhost:8787)を表示するだけ。
// 機能はすべて Python core 側。Electron は「窓と tray」だけを担う(引き算)。
// ミニ監視窓: 最前面の小窓(/mini)を tray クリック / Cmd+Shift+B でポップアップ。
const { app, BrowserWindow, Tray, Menu, nativeImage, shell, globalShortcut } = require('electron');
const path = require('path');
const http = require('http');
const os = require('os');
const { spawn } = require('child_process');

const PORT = 8787;
const DASH_URL = `http://127.0.0.1:${PORT}`;
const PROJECT = '/Users/shigenoburyuto/Documents/GitHub/tool_dev_SGNB/brain_tact';
const VENV_PY = path.join(os.homedir(), '.venvs/brain_tact/bin/python');

let win = null;
let miniWin = null;
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

// ミニ監視窓 — 常に最前面・全ワークスペース表示の簡易窓。
// 「全体監視が行き届かない」対策: 作業中でも視界の隅に置ける/即ポップアップできる
function createMiniWindow() {
  miniWin = new BrowserWindow({
    width: 340,
    height: 460,
    minWidth: 260,
    minHeight: 200,
    frame: false,
    alwaysOnTop: true,
    backgroundColor: '#14161a',
    icon: path.join(__dirname, 'icon.png'),
    skipTaskbar: true,
    show: false,
  });
  miniWin.setAlwaysOnTop(true, 'floating');
  miniWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  miniWin.loadURL(`${DASH_URL}/mini`);
  // ミニ内のリンク(⤢フル)はフルダッシュボード窓で開く
  miniWin.webContents.setWindowOpenHandler(() => {
    win.show();
    win.focus();
    return { action: 'deny' };
  });
  miniWin.on('close', (e) => {
    if (!app.isQuitting) { e.preventDefault(); miniWin.hide(); }
  });
}

function toggleMini() {
  if (!miniWin) createMiniWindow();
  if (miniWin.isVisible()) miniWin.hide();
  else { miniWin.show(); miniWin.focus(); }
}

function createTray() {
  const img = nativeImage
    .createFromPath(path.join(__dirname, 'icon.png'))
    .resize({ width: 18, height: 18 });
  tray = new Tray(img);
  tray.setToolTip('brain_tact — critique-first supervisor (click: ミニ監視)');
  tray.on('click', toggleMini);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'ミニ監視 (⌘⇧B)', click: toggleMini },
    { label: 'フルダッシュボード', click: () => { win.show(); win.focus(); } },
    { label: 'ブラウザで開く', click: () => shell.openExternal(DASH_URL) },
    { label: '再読み込み', click: () => { win.reload(); if (miniWin) miniWin.reload(); } },
    { type: 'separator' },
    { label: '終了', click: () => { app.isQuitting = true; app.quit(); } },
  ]));
}

app.whenReady().then(() => {
  ping((up) => {
    if (!up) startSidecar();
    // 常駐済みなら即、サイドカー起動なら立ち上がりを待つ
    setTimeout(() => {
      createWindow();
      createMiniWindow();
      createTray();
      // どのアプリにいてもミニ監視を出し入れできる
      globalShortcut.register('CommandOrControl+Shift+B', toggleMini);
    }, up ? 0 : 1800);
  });
  app.on('activate', () => { if (win) { win.show(); win.focus(); } });
});

app.on('will-quit', () => globalShortcut.unregisterAll());

app.on('before-quit', () => {
  app.isQuitting = true;
  if (sidecar) sidecar.kill();
});
app.on('window-all-closed', () => {}); // tray で常駐し続ける
