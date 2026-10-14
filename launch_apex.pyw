"""One-click APEX for Windows: double-click to open, run with --stop to stop.

Opens http://localhost:7842/ in your browser. If the server is not running yet,
starts it in the background first (no console window; output goes to
apex.log beside this file) and waits until it answers. Running it again while
the server is up just opens the browser.

Desktop shortcuts point here, run by the project's own pythonw.exe:
  APEX       .venv\\Scripts\\pythonw.exe launch_apex.pyw
  Stop APEX  .venv\\Scripts\\pythonw.exe launch_apex.pyw --stop
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get('APEX_PORT', '7842'))
URL = f'http://localhost:{PORT}/'
PID_FILE = HERE / 'apex.pid'
LOG_FILE = HERE / 'apex.log'


def running():
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/health', timeout=2) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 503                 # up, but reporting a problem: still running
    except OSError:
        return False


def message(text, title='APEX'):
    """A small Windows message box (this script has no console to print to)."""
    if '--quiet' in sys.argv:
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    except Exception:
        pass


def start():
    python = HERE / '.venv' / 'Scripts' / 'python.exe'
    if not python.exists():
        python = Path(sys.executable)
    log = open(LOG_FILE, 'a', encoding='utf-8')
    log.write(f'\n=== started {time.strftime("%Y-%m-%d %H:%M:%S")} ===\n')
    log.flush()
    flags = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    proc = subprocess.Popen([str(python), str(HERE / 'agent_server.py')], cwd=HERE, stdout=log,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags,
                            env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    PID_FILE.write_text(str(proc.pid), encoding='utf-8')
    for _ in range(60):                    # up to 30 s
        if running():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.5)
    return running()


def stop():
    if not PID_FILE.exists():
        message('APEX is not running from this launcher.' if not running() else
                'APEX is running, but it was not started by this launcher.\n'
                'Close the window it is running in, or press Ctrl+C there.')
        return
    pid = PID_FILE.read_text(encoding='utf-8').strip()
    subprocess.run(['taskkill', '/PID', pid, '/T', '/F'], capture_output=True,
                   creationflags=0x08000000)
    PID_FILE.unlink(missing_ok=True)
    message('APEX stopped.')


def main():
    if '--stop' in sys.argv:
        stop()
        return
    if not running() and not start():
        message(f'APEX could not start. Details are in:\n{LOG_FILE}', 'APEX - error')
        return
    if '--no-browser' not in sys.argv:
        webbrowser.open(URL)


if __name__ == '__main__':
    main()
