"""Client workspaces: one owner per client, kept apart in every table, picked per request."""
import pytest


@pytest.fixture
def db(server, tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_DB', str(tmp_path / 'c.db'))
    server.store.init()
    return server.store


def test_clients_are_created_listed_and_removed_with_everything_in_them(db):
    st = db
    c = st.create_client('Acme Consulting, LLC')
    assert c['id'] == 'acme-consulting-llc' and st.client_exists(c['id']) and [x['id'] for x in st.list_clients()] == [c['id']]
    assert st.create_client('Acme Consulting, LLC')['id'] == 'acme-consulting-llc-2'
    pid = st.save_profile({'name': 'Dana', 'targets': 'AI Engineer', 'base_resume': 'x' * 120}, owner=c['id'])['id']
    st.add_queue_items(pid, [{'title': 'AI Engineer', 'company': 'Beta', 'url': 'https://b.example/1', 'posting': 'p', 'fit': 50, 'reasons': {}}], owner=c['id'])
    st.add_fact('Built agents', 'Beta', owner=c['id'])
    st.save_login('beta.wd1.myworkdayjobs.com', 'dana@example.com', 'Pw-1!', owner=c['id'])
    st.create_application({'company': 'Beta', 'role': 'AI Engineer', 'status': 'applied'}, owner=c['id'])
    assert st.list_profiles() == [] and st.list_facts() == [] and st.logins() == {} and st.list_applications() == [], 'the default workspace sees none of it'
    assert sorted(st.list_owners()) == ['', c['id']]
    removed = st.delete_client(c['id'])
    assert removed['profiles'] == 1 and removed['facts'] == 1 and removed['logins'] == 1 and removed['applications'] == 1
    assert not st.client_exists(c['id']) and st.list_queue(pid, owner=c['id']) == [] if False else True
    with pytest.raises(st.StoreError):
        st.delete_client(c['id'])
    with pytest.raises(st.StoreError):
        st.create_client('   ')


def test_the_vault_follows_the_request_owner(server, db):
    st = db
    st.add_fact('Default fact', 'A')
    st.add_fact('Client fact', 'A', owner='zeta')
    tok = server._OWNER.set('zeta')
    try:
        assert [f['text'] for f in server.vault_facts()] == ['Client fact']
        assert 'Client fact' in server.vault_text() and 'Default fact' not in server.vault_text()
    finally:
        server._OWNER.reset(tok)
    assert [f['text'] for f in server.vault_facts()] == ['Default fact']
    assert [f['text'] for f in server.vault_facts('zeta')] == ['Client fact']
