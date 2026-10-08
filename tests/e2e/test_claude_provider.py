"""APEX on Claude: the full Launch flow through the anthropic SDK (offline stub)."""
import json
import http.client
import uuid

import pytest

anthropic = pytest.importorskip('anthropic', reason='pip install -r requirements.txt')


def test_full_run_on_claude_models(claude_app, fake_openai, fixture_resume):
    before = len(fake_openai.calls)
    c = http.client.HTTPConnection('127.0.0.1', claude_app.port, timeout=300)
    title = 'Senior Data Analyst ' + uuid.uuid4().hex[:5]
    c.request('POST', '/analyze', body=json.dumps({'jobTitle': title, 'industry': 'general', 'seniority': 'senior',
                                                   'resume': fixture_resume}),
              headers={'Host': f'localhost:{claude_app.port}', 'Content-Type': 'application/json'})
    r = c.getresponse()
    events = [json.loads(f[6:]) for f in r.read().split(b'\n\n') if f.startswith(b'data: ')]
    types = [e['type'] for e in events]
    assert 'error' not in types, [e for e in events if e['type'] == 'error']
    eng = next(e['data'] for e in events if e['type'] == 'engine_data')
    assert [c_['id'] for c_ in eng['changes']] == ['S', 'B1', 'B2']
    assert (eng['score']['before'], eng['score']['after']) == (48, 74)

    calls = fake_openai.calls[before:]
    assert calls and all(x['provider'] == 'anthropic' for x in calls), {x['provider'] for x in calls}
    models = {x['model'] for x in calls}
    assert models == {'claude-sonnet-5-5', 'claude-haiku-5-5'}, models
    for x in calls:   # current Claude models reject temperature; thinking depth is set via output_config.effort
        assert 'temperature' not in x['body_keys'] and 'output_config' in x['body_keys'], x['body_keys']

    cost = next(e['data'] for e in events if e['type'] == 'cost_data')
    assert cost['measured'] and cost['calls'] == len(calls) and cost['est_usd'] > 0


def test_claude_parse_failure_is_reported(claude_app):
    c = http.client.HTTPConnection('127.0.0.1', claude_app.port, timeout=60)
    c.request('POST', '/parse-resume', body=json.dumps({'resume': 'Jane Doe\nEXPERIENCE\n- did FAILPARSE things'}),
              headers={'Host': f'localhost:{claude_app.port}', 'Content-Type': 'application/json'})
    r = c.getresponse()
    j = json.loads(r.read())
    assert r.status == 500 and 'Anthropic 400' in j['error'] and 'stubbed failure' in j['error']


def test_anthropic_only_config_with_a_creative_key_name(tmp_path_factory, fake_openai, fixture_resume):
    """The owner's real setup: only an Anthropic key, written as "Anthropic_API_KEy".
    APEX must find it, default to Claude, and explain that voice needs OpenAI."""
    from conftest import ServerProcess
    app = ServerProcess(tmp_path_factory, fake_openai, config_json={'Anthropic_API_KEy': 'sk-ant-test-stub'},
                        extra_env={'APEX_ANTHROPIC_BASE': fake_openai.url})
    try:
        assert 'Keys loaded (Anthropic)' in app.log()
        before = len(fake_openai.calls)
        c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=300)
        c.request('POST', '/parse-resume', body=json.dumps({'resume': fixture_resume}),
                  headers={'Host': f'localhost:{app.port}', 'Content-Type': 'application/json'})
        r = c.getresponse(); r.read()
        assert r.status == 200
        assert {x['model'] for x in fake_openai.calls[before:]} == {'claude-opus-5-5'}
        c = http.client.HTTPConnection('127.0.0.1', app.port, timeout=30)
        c.request('POST', '/transcribe', body=json.dumps({'audio_b64': 'AAAA'}),
                  headers={'Host': f'localhost:{app.port}', 'Content-Type': 'application/json'})
        r = c.getresponse(); j = json.loads(r.read())
        assert r.status == 400 and 'needs an OpenAI key' in j['error']
    finally:
        app.stop()
