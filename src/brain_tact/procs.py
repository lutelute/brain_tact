"""psとlsofによるclaudeプロセスの検出と作業ディレクトリ解決。

検出ルール(実機確認済み):
- コマンドのbasenameが `claude` で始まる行(plain `claude` 起動も拾う —
  watchdogの固定文字列grepは8セッション中3つを見逃していた)
- `-p` / `--print` をトークンとして含むもの(brain自身のヘッドレス起動)は除外
- tty `??` (デーモン系)は除外
- 各セッションのtty上にはwatchdog MCP子プロセス(python)も居るが、
  basename一致なので誤検出しない
"""

import subprocess
from dataclasses import dataclass


@dataclass
class ClaudeProc:
    pid: int
    tty: str            # /dev/ttys003 形式
    cpu_pct: float      # 0.0=アイドル傾向 / 1.4〜8 =活動中(実測)
    etime: str          # ps表記のまま(例 01:34:29)
    etime_min: float
    lstart: str
    cmd: str
    cwd: str | None = None


def _etime_to_min(etime: str) -> float:
    """ps etime([[dd-]hh:]mm:ss)を分に変換する。"""
    days = 0
    if "-" in etime:
        d, etime = etime.split("-", 1)
        days = int(d)
    parts = [int(p) for p in etime.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return days * 1440 + h * 60 + m + s / 60


def find_claude_processes() -> dict[str, ClaudeProc]:
    """tty(/dev/ttysNNN) -> ClaudeProc。cwdも解決済みで返す。"""
    result = subprocess.run(
        ["ps", "-axww", "-o", "pid=,tty=,pcpu=,etime=,lstart=,command="],
        capture_output=True, text=True, timeout=15,
    )
    procs: dict[str, ClaudeProc] = {}
    for line in result.stdout.splitlines():
        # pid tty pcpu etime + lstart(5トークン: 曜 月 日 時刻 年) + command(残り)
        t = line.split(None, 9)
        if len(t) < 10:
            continue
        pid_s, tty, pcpu, etime = t[0], t[1], t[2], t[3]
        lstart = " ".join(t[4:9])
        cmd = t[9]

        argv = cmd.split()
        if not argv:
            continue
        if argv[0].rsplit("/", 1)[-1] != "claude":
            continue
        if {"-p", "--print"} & set(argv):
            continue  # ヘッドレス(brain自身)は対象外
        if tty == "??":
            continue

        try:
            procs[f"/dev/{tty}"] = ClaudeProc(
                pid=int(pid_s),
                tty=f"/dev/{tty}",
                cpu_pct=float(pcpu),
                etime=etime,
                etime_min=_etime_to_min(etime),
                lstart=lstart,
                cmd=cmd,
            )
        except ValueError:
            continue

    _attach_cwds(procs)
    return procs


def _attach_cwds(procs: dict[str, ClaudeProc]) -> None:
    """lsofの複数PID一括指定(-p 1,2,3 -Fpn)でcwdをまとめて解決する。"""
    if not procs:
        return
    pids = ",".join(str(p.pid) for p in procs.values())
    # launchd環境はPATHが細い(/usr/sbinが無いとlsofが見つからない)のでフルパス指定
    result = subprocess.run(
        ["/usr/sbin/lsof", "-a", "-p", pids, "-d", "cwd", "-Fpn"],
        capture_output=True, text=True, timeout=30,
    )
    by_pid = {p.pid: p for p in procs.values()}
    cur: int | None = None
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            cur = int(line[1:])
        elif line.startswith("n") and cur in by_pid:
            by_pid[cur].cwd = line[1:]
