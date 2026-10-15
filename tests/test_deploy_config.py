"""Static checks on the deployment files: the image can't carry secrets or data,
and the demo is configured the way DEPLOY.md says."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_FILES = ['agent_server.py', 'apex_engine.py', 'apex_domains.py', 'apex_apply.py', 'apex_store.py', 'index.html']
FONTS = ['assets/NotoSans-Bold.ttf', 'assets/NotoSans-Regular.ttf']
LICENCE = 'assets/OFL.txt'


def test_dockerignore_is_an_allowlist_of_the_app_files():
    lines = [l.strip() for l in (ROOT / '.dockerignore').read_text().splitlines() if l.strip() and not l.startswith('#')]
    assert lines[0] == '*'
    assert sorted(lines[1:]) == sorted(['!' + f for f in APP_FILES + FONTS + [LICENCE, 'requirements.txt']])
    assert 'SIL OPEN FONT LICENSE' in (ROOT / LICENCE).read_text(encoding='utf-8').upper()
    for f in FONTS:
        assert (ROOT / f).is_file() and (ROOT / f).read_bytes()[:4] in (b'\x00\x01\x00\x00', b'true', b'OTTO'), f


def test_dockerfile_copies_only_app_files_and_drops_root():
    df = (ROOT / 'Dockerfile').read_text()
    copies = re.findall(r'^COPY (.+)$', df, re.M)
    assert copies == ['requirements.txt ./', 'agent_server.py apex_store.py apex_engine.py apex_domains.py apex_apply.py index.html ./',
                      'assets/NotoSans-Regular.ttf assets/NotoSans-Bold.ttf assets/OFL.txt ./assets/']
    assert 'pip install --no-cache-dir -r requirements.txt' in df
    assert 'setpriv --reuid=10001' in df and 'APEX_BIND=0.0.0.0' in df and 'APEX_DB=/data/apex.db' in df
    assert 'APEX_TRUST_PROXY' not in re.sub(r'#.*', '', df), 'proxy trust belongs to the platform config, not the image'


def test_fly_config_single_volume_https_health_and_no_secrets():
    t = tomllib.loads((ROOT / 'fly.toml').read_text())
    svc = t['http_service']
    assert svc['force_https'] is True and svc['internal_port'] == 8080
    assert [c['path'] for c in svc['checks']] == ['/health']
    assert t['mounts'][0]['destination'] == '/data'
    env = t['env']
    assert env['APEX_TRUST_PROXY'] == '1' and env['APEX_MODEL'].startswith('claude-')
    secretish = [k for k in env if re.search(r'KEY|SECRET|ACCESS_CODE|PASS', k)]
    assert not secretish, f'secrets belong in `fly secrets`, not fly.toml: {secretish}'
