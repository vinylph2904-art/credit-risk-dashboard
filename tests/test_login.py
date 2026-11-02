"""Login must gate data, rotate the session token and keep redirects local."""
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import pytest
from auth_database import AuthDatabase

import web.app as web_app
from web import runtime


@pytest.fixture
def client(monkeypatch):
    app = web_app.app
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setitem(app.view_functions, 'dashboard', lambda: 'private-workspace')
    database = AuthDatabase()
    monkeypatch.setattr(runtime, 'get_db', lambda: database)
    return app.test_client()


def token(client):
    page = client.get('/login')
    assert page.status_code == 200
    return BeautifulSoup(page.data, 'html.parser').select_one('[name=csrf_token]')['value']


def sign_in(client, next_url='/'):
    csrf = token(client)
    return client.post('/login', data={'username':'analyst_test', 'password':'test-password!',
        'csrf_token':csrf, 'next':next_url}), csrf


def test_login_is_public_and_separate_from_dashboard(client):
    response = client.get('/login')
    page = BeautifulSoup(response.data, 'html.parser')
    assert response.status_code == 200
    assert page.select_one('#login-form')
    assert page.select_one('input[type=password][autocomplete=current-password]')
    assert not page.select_one('.sidebar')
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/static/login.css').status_code == 200


def test_login_omits_logo_and_serves_its_styles_without_authentication(client):
    page = BeautifulSoup(client.get('/login').data, 'html.parser')
    assert not page.select_one('.login-brand-logo, img, link[rel=icon]')
    stylesheet = page.select_one('link[rel=stylesheet]')['href']
    response = client.get(stylesheet)
    assert response.status_code == 200 and response.mimetype == 'text/css'


@pytest.mark.parametrize('path', ['/', '/risk?segment=income', '/applications', '/model', '/history', '/analysis/records'])
def test_unauthenticated_pages_redirect_before_reading_data(client,path):
    response = client.get(path)
    assert response.status_code == 302
    assert urlsplit(response.location).path == '/login'
    assert parse_qs(urlsplit(response.location).query)['next'] == [path]


def test_unauthenticated_api_and_mutations_return_401(client):
    assert client.get('/api/dashboard').status_code == 401
    response = client.post('/api/scenarios/profiles/1', json={'changes':{}})
    assert response.status_code == 401
    assert 'login_url' in response.json


def test_login_requires_csrf_and_uses_login_error_screen(client):
    response = client.post('/login', data={'username':'analyst_test','password':'test-password!'})
    assert response.status_code == 400
    assert b'login-form' in response.data
    with client.session_transaction() as state:
        assert 'auth_user' not in state


@pytest.mark.parametrize('username,password', [('analyst_test','wrong-password'),('unknown','test-password!'),('tên-khác','wrong')])
def test_invalid_login_has_generic_error_and_never_echoes_password(client,username,password):
    response = client.post('/login', data={'username':username,'password':password,'csrf_token':token(client)})
    assert response.status_code == 401
    page = BeautifulSoup(response.data,'html.parser')
    assert page.select_one('[role=alert]')
    assert not page.select_one('#password').has_attr('value')
    assert password not in page.get_text()
    with client.session_transaction() as state:
        assert 'auth_user' not in state


def test_login_rotates_csrf_and_preserves_local_destination(client):
    response, old_token = sign_in(client,'/risk?segment=income')
    assert response.status_code == 302
    assert response.location == '/risk?segment=income'
    with client.session_transaction() as state:
        assert state['auth_user'] == 'analyst_test'
        assert state['csrf_token'] != old_token
        assert state.permanent
    assert client.get('/').data == b'private-workspace'


@pytest.mark.parametrize('destination', ['https://example.org', '//example.org', '/\\example.org',
    '/%2fexample.org', '/%0d%0aLocation:evil', '/login', '/logout'])
def test_login_cannot_redirect_to_external_or_auth_destinations(client,destination):
    response,_ = sign_in(client,destination)
    assert response.status_code == 302
    assert response.location == '/'


def test_logout_requires_post_and_current_csrf_and_revokes_access(client):
    _, old_token = sign_in(client)
    assert client.get('/logout').status_code == 405
    assert client.post('/logout',data={'csrf_token':old_token}).status_code == 400
    with client.session_transaction() as state:
        current_token = state['csrf_token']
    response = client.post('/logout',data={'csrf_token':current_token})
    assert response.status_code == 302 and response.location == '/login'
    assert client.get('/').status_code == 302
    assert client.get('/api/dashboard').status_code == 401
    with client.session_transaction() as state:
        assert 'auth_user' not in state
