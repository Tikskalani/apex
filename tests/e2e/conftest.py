"""Fixtures for the APEX browser suite.

The app under test is a copy of agent_server.py + index.html in a temp dir with
a stub config.json, so the suite never reads or exposes the real keys, and
every OpenAI call goes to tests/e2e/fake_openai.py. CDN libraries (jsPDF,
docx, pdf.js, mammoth) still load from cdnjs/jsDelivr, so the suite needs a
network connection, exactly like the app does.
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from fake_openai import FakeOpenAI

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RESUME = (Path(__file__).parent / 'fixtures' / 'marcus_delgado.txt').read_text(encoding='utf-8')


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture(scope='session')
def fake_openai():
    with FakeOpenAI() as f:
        yield f


class ServerProcess:
    """A copy of the app in a temp dir, started with the given extra env."""

    def __init__(self, tmp_path_factory, fake_openai, extra_env=None, config=True):
        d = tmp_path_factory.mktemp('apex')
        for name in ('agent_server.py', 'apex_store.py', 'index.html'):
            shutil.copy(ROOT / name, d / name)
        env = dict(os.environ, APEX_OPENAI_BASE=fake_openai.url)
        if config:
            (d / 'config.json').write_text(json.dumps({'OPENAI_KEY': 'sk-test-stub-not-a-real-key', 'JSEARCH_KEY': ''}))
        else:
            env['OPENAI_API_KEY'] = 'sk-test-stub-not-a-real-key'     # how a container gets its key
        self.port = _free_port()
        env['APEX_PORT'] = str(self.port)
        env.update(extra_env or {})
        self.dir, self.url = d, f'http://localhost:{self.port}'
        self._log_path = d / 'server.log'
        self._log = open(self._log_path, 'w', encoding='utf-8')
        self.proc = subprocess.Popen([sys.executable, '-I', str(d / 'agent_server.py')], cwd=d, env=env,
                                     stdout=self._log, stderr=subprocess.STDOUT)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.proc.poll() is not None:
                pytest.fail(f'agent_server.py exited with {self.proc.returncode}:\n{self.log()}')
            try:
                c = http.client.HTTPConnection('localhost', self.port, timeout=1)
                c.request('GET', '/health')
                if c.getresponse().status == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            self.proc.kill()
            pytest.fail(f'agent_server.py did not answer /health within 20s:\n{self.log()}')

    def log(self):
        return self._log_path.read_text(encoding='utf-8', errors='replace')

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._log.close()


@pytest.fixture(scope='session')
def app(tmp_path_factory, fake_openai):
    """The app as you run it locally. Yields .url, .port, .dir, .log()."""
    a = ServerProcess(tmp_path_factory, fake_openai)
    yield a
    a.stop()


HOSTED_CODE = 'correct-horse-battery-staple'
HOSTED_HOST = 'apex-demo.example.test'


@pytest.fixture(scope='session')
def hosted(tmp_path_factory, fake_openai):
    """The app as the public demo runs it: access code, signed sessions,
    per-visitor budget (small here so the limit is testable), proxy IP trust."""
    a = ServerProcess(tmp_path_factory, fake_openai, config=False, extra_env={
        'APEX_ACCESS_CODE': HOSTED_CODE, 'APEX_SESSION_SECRET': 'x' * 48,
        'APEX_PUBLIC_HOST': HOSTED_HOST, 'APEX_TRUST_PROXY': '1',
        'APEX_VISITOR_BUDGET': '3', 'APEX_DAILY_BUDGET': '1000'})
    a.code, a.public_host = HOSTED_CODE, HOSTED_HOST
    yield a
    a.stop()


def _headless_pids():
    """PIDs of Playwright's headless Chromium (never the user's chrome.exe)."""
    if os.name != 'nt':
        return set()
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq headless_shell.exe', '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True).stdout
    return {int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"headless_shell')}


@pytest.fixture(scope='session')
def browser():
    before = _headless_pids()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=os.environ.get('APEX_HEADED') != '1')
        yield b
        b.close()
    # On Windows the driver can exit before Chromium finishes shutting down,
    # orphaning a process per run. Give it a moment, then reap only the
    # headless_shell processes this session started.
    deadline = time.time() + 10
    while (left := _headless_pids() - before) and time.time() < deadline:
        time.sleep(0.5)
    for pid in left:
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)


class PageProbe:
    """A page plus everything it said to the console."""
    def __init__(self, page):
        self.page = page
        self.console_errors, self.console_warnings, self.page_errors = [], [], []
        page.on('console', self._console)
        page.on('pageerror', lambda e: self.page_errors.append(str(e)))

    def _console(self, msg):
        if msg.type == 'error':
            self.console_errors.append(msg.text)
        elif msg.type == 'warning':
            self.console_warnings.append(msg.text)

    def assert_clean(self):
        assert not self.page_errors, f'uncaught exceptions: {self.page_errors}'
        assert not self.console_errors, f'console errors: {self.console_errors}'


@pytest.fixture
def probe(browser, app):
    ctx = browser.new_context(accept_downloads=True, viewport={'width': 1440, 'height': 900})
    page = ctx.new_page()
    pp = PageProbe(page)
    page.goto(app.url + '/')
    # The page is ready once its own health check has rendered the version.
    page.wait_for_function("document.getElementById('tel-server-v').textContent === '10.0'", timeout=15000)
    yield pp
    ctx.close()


@pytest.fixture
def fixture_resume():
    return FIXTURE_RESUME
