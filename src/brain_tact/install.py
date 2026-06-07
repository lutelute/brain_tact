"""launchd plist と /brain スキルのインストール。"""

import shutil
import subprocess
import sys
from pathlib import Path

from . import BRAIN_DIR

PLIST_SRC = BRAIN_DIR / "launchd" / "com.sgnb.brain-tact.plist"
PLIST_DST = Path.home() / "Library" / "LaunchAgents" / "com.sgnb.brain-tact.plist"
SKILL_SRC = BRAIN_DIR / "skills" / "brain"
SKILL_DST = Path.home() / ".claude" / "skills" / "brain"
CYCLE_SH = BRAIN_DIR / "bin" / "brain-cycle.sh"


def install_launchd(dry: bool = False) -> int:
    if not PLIST_SRC.exists():
        print(f"❌ plistが見つかりません: {PLIST_SRC}", file=sys.stderr)
        return 1
    if dry:
        print(f"[dry] cp {PLIST_SRC} → {PLIST_DST} && launchctl load")
        return 0

    CYCLE_SH.chmod(0o755)
    PLIST_DST.parent.mkdir(parents=True, exist_ok=True)

    # 既ロードなら一旦unload(plist更新の反映)
    subprocess.run(["launchctl", "unload", str(PLIST_DST)],
                   capture_output=True, text=True)
    shutil.copy2(PLIST_SRC, PLIST_DST)
    result = subprocess.run(["launchctl", "load", str(PLIST_DST)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ launchctl load 失敗: {result.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"✅ LaunchAgent登録: {PLIST_DST}")
    print("   発火時刻: 7:00 / 12:00 / 17:00 / 22:00")
    print("   手動発火テスト: launchctl kickstart -k "
          "gui/$(id -u)/com.sgnb.brain-tact")
    return 0


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
