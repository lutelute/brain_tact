"""launchd plist と /brain スキルのインストール。"""

import shutil
import subprocess
import sys
from pathlib import Path

from . import BRAIN_DIR

LA = Path.home() / "Library" / "LaunchAgents"
PLIST_SRC = BRAIN_DIR / "launchd" / "com.sgnb.brain-tact.plist"
PLIST_DST = LA / "com.sgnb.brain-tact.plist"
DASH_SRC = BRAIN_DIR / "launchd" / "com.sgnb.brain-tact-dashboard.plist"
DASH_DST = LA / "com.sgnb.brain-tact-dashboard.plist"
SKILL_SRC = BRAIN_DIR / "skills" / "brain"
SKILL_DST = Path.home() / ".claude" / "skills" / "brain"
CYCLE_SH = BRAIN_DIR / "bin" / "brain-cycle.sh"


def _load_agent(src: Path, dst: Path, label: str) -> bool:
    """plistを配置してload(既ロードなら入れ替え)。成功でTrue。"""
    subprocess.run(["launchctl", "unload", str(dst)], capture_output=True, text=True)
    shutil.copy2(src, dst)
    r = subprocess.run(["launchctl", "load", str(dst)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"❌ {label} load失敗: {r.stderr.strip()}", file=sys.stderr)
        return False
    return True


def install_launchd(dry: bool = False) -> int:
    if not PLIST_SRC.exists():
        print(f"❌ plistが見つかりません: {PLIST_SRC}", file=sys.stderr)
        return 1
    if dry:
        print(f"[dry] cp {PLIST_SRC} → {PLIST_DST} && launchctl load")
        return 0

    CYCLE_SH.chmod(0o755)
    LA.mkdir(parents=True, exist_ok=True)

    ok1 = _load_agent(PLIST_SRC, PLIST_DST, "定時巡回")
    ok2 = _load_agent(DASH_SRC, DASH_DST, "ダッシュボード")
    if ok1:
        print(f"✅ 定時巡回: {PLIST_DST.name}(7/12/17/22時)")
        print("   手動発火: launchctl kickstart -k gui/$(id -u)/com.sgnb.brain-tact")
    if ok2:
        print(f"✅ ダッシュボード常駐: http://127.0.0.1:8787/")
    return 0 if (ok1 and ok2) else 1


def install_skill(dry: bool = False) -> int:
    if not (SKILL_SRC / "SKILL.md").exists():
        print(f"❌ スキルが見つかりません: {SKILL_SRC}/SKILL.md", file=sys.stderr)
        return 1
    if dry:
        print(f"[dry] cp -r {SKILL_SRC} → {SKILL_DST}")
        return 0
    SKILL_DST.mkdir(parents=True, exist_ok=True)
    for f in SKILL_SRC.iterdir():
        if f.is_file():
            shutil.copy2(f, SKILL_DST / f.name)
    print(f"✅ /brain スキル配置: {SKILL_DST}")
    return 0
