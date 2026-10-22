"""Start a single closing-bet daemon as detached process."""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / '.venv' / 'Scripts' / 'python.exe'
SCRIPT = ROOT / 'scripts' / 'direct_closing_bet.py'
LOG = ROOT / 'logs' / 'closing_bet' / 'closing_bet.log'
LOG.parent.mkdir(parents=True, exist_ok=True)

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

with open(LOG, 'a', encoding='utf-8', errors='replace') as lf:
    proc = subprocess.Popen(
        [str(PYTHON), str(SCRIPT), '--daemon'],
        stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        cwd=str(ROOT),
        close_fds=True,
    )
print(f'daemon 시작 PID: {proc.pid}')

time.sleep(6)

import psutil
real_daemons = []
for p in psutil.process_iter(['pid', 'cmdline', 'exe']):
    try:
        cmd = p.info['cmdline'] or []
        exe = (p.info.get('exe') or '').lower()
        if not exe.endswith('python.exe'):
            continue
        # exact match: only treat as daemon if it's running direct_closing_bet.py with --daemon
        if any('direct_closing_bet.py' in c for c in cmd) and '--daemon' in cmd:
            real_daemons.append(p.info['pid'])
    except Exception:
        pass

print(f'확인된 daemon 개수: {len(real_daemons)} → PIDs: {real_daemons}')
