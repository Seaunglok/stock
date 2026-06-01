"""Kill all running direct_closing_bet --daemon processes."""
import psutil
import subprocess
import time

pids = []
for p in psutil.process_iter(['pid', 'cmdline']):
    try:
        cmd = ' '.join(p.info['cmdline'] or [])
        if 'direct_closing_bet.py' in cmd and '--daemon' in cmd:
            pids.append(p.info['pid'])
    except Exception:
        pass

print(f'kill 대상: {len(pids)}개 → {pids}')

for pid in pids:
    try:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True, check=False)
        print(f'  taskkill /F /PID {pid}')
    except Exception as e:
        print(f'  PID {pid} 실패: {e}')

time.sleep(3)

remaining = []
for p in psutil.process_iter(['pid', 'cmdline']):
    try:
        cmd = ' '.join(p.info['cmdline'] or [])
        if 'direct_closing_bet.py' in cmd and '--daemon' in cmd:
            remaining.append(p.info['pid'])
    except Exception:
        pass

print(f'남은 daemon: {remaining}')
