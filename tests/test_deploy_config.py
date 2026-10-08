"""Static checks on the deployment files: the image can't carry secrets or data."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dockerignore_is_an_allowlist_of_the_app_files():
    lines = [l.strip() for l in (ROOT / '.dockerignore').read_text().splitlines() if l.strip() and not l.startswith('#')]
    assert lines[0] == '*'
    assert sorted(lines[1:]) == ['!agent_server.py', '!apex_engine.py', '!apex_store.py', '!index.html',
                                 '!requirements.txt']


def test_dockerfile_copies_only_app_files_and_drops_root():
    df = (ROOT / 'Dockerfile').read_text()
    copies = re.findall(r'^COPY (.+)$', df, re.M)
    assert copies == ['requirements.txt ./', 'agent_server.py apex_store.py apex_engine.py index.html ./']
    assert 'pip install --no-cache-dir -r requirements.txt' in df
    assert 'setpriv --reuid=10001' in df and 'APEX_BIND=0.0.0.0' in df and 'APEX_DB=/data/apex.db' in df


def test_fly_config_single_volume_https_and_health():
    t = (ROOT / 'fly.toml').read_text()
    assert 'force_https          = true' in t and 'path         = "/health"' in t
    assert 'destination = "/data"' in t and 'internal_port        = 8080' in t
    assert 'OPENAI' not in t and 'ACCESS_CODE' not in t, 'secrets belong in `fly secrets`, not fly.toml'
