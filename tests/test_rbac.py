"""Kiểm tra phân quyền chức năng, hồ sơ và thu hồi phiên đăng nhập."""
from bs4 import BeautifulSoup
import pandas as pd
import pytest

import web.app as web_app
from web import runtime
from auth_database import AuthDatabase
from web.auth import COMMON, MANAGER, ADMIN


@pytest.fixture
def setup(monkeypatch):
    db = AuthDatabase()
    monkeypatch.setitem(web_app.app.config,'TESTING',True)
    monkeypatch.setattr(runtime,'get_db',lambda:db)
    return web_app.app.test_client(), db, monkeypatch


def login(client, username='analyst_test'):
    csrf = BeautifulSoup(client.get('/login').data,'html.parser').select_one('[name=csrf_token]')['value']
    response = client.post('/login',data={'username':username,'password':'test-password!','csrf_token':csrf})
    assert response.status_code == 302
    with client.session_transaction() as state:
        return state['csrf_token']


def test_all_routes_have_explicit_policy():
    endpoints = {rule.endpoint for rule in web_app.app.url_map.iter_rules()}
    assert endpoints <= COMMON | MANAGER | ADMIN | {'login','static','plotly_javascript','brand_logo'}


@pytest.mark.parametrize('username', ['analyst_test', 'risk_manager', 'admin'])
def test_account_is_a_page_for_the_signed_in_user(setup, username):
    client, db, patch = setup
    csrf = login(client, username)
    response = client.get('/account')
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser')
    assert page.select_one('.sidebar-user[aria-current="page"]')['href'] == '/account'
    assert page.select_one('.account-information').select('dd')[1].get_text(strip=True) == username
    assert page.select_one('.account-actions a')['href'] == '/account/password'
    logout = page.select_one('.account-actions form')
    assert logout['method'] == 'post' and logout['action'] == '/logout'
    assert logout.select_one('[name="csrf_token"]')['value'] == csrf
    assert page.select_one('.sidebar-account-panel') is None


def test_account_requires_login(setup):
    client, db, patch = setup
    response = client.get('/account')
    assert response.status_code == 302
    assert '/login?next=/account' in response.location


@pytest.mark.parametrize('role,visible', [('risk_manager',True),('analyst_test',False),('admin',False)])
def test_history_navigation_is_manager_only_and_keeps_cohort_filters(setup,role,visible):
    client,db,patch=setup
    login(client,role)
    # Use the actual base template/context without loading financial source tables.
    from flask import render_template
    patch.setitem(web_app.app.view_functions,'change_password',lambda:render_template('error.html',message='test',code=200))
    response=client.get('/account/password?product=Cash+loans&income=Working')
    assert response.status_code==200
    page=BeautifulSoup(response.data,'html.parser')
    for route in ['/diagnostics','/payments']:
        links=[a for a in page.select('.sidebar a[href]') if a['href'].split('?')[0]==route]
        assert bool(links)==visible
        if visible:
            from urllib.parse import parse_qs,urlsplit
            params=parse_qs(urlsplit(links[0]['href']).query)
            assert params['product']==['Cash loans'] and params['income']==['Working']


@pytest.mark.parametrize('path',['/admin/users','/admin/audit','/analysis/records','/analysis/applications/100001',
    '/diagnostics','/payments','/risk/diagnostics','/api/dashboard','/api/dashboard/details','/api/scenarios/portfolio','/applications/template'])
def test_analyst_cannot_use_management_or_unrestricted_diagnostics(setup,path):
    client,db,patch = setup
    login(client)
    assert client.get(path).status_code == 403


@pytest.mark.parametrize('path',['/risk','/applications','/model','/history','/analysis/records','/api/dashboard','/api/scenarios/portfolio','/applications/10'])
def test_admin_has_no_credit_data_access(setup,path):
    client,db,patch=setup
    login(client,'admin')
    assert client.get(path).status_code == 403
    assert client.get('/').location.endswith('/admin/users')


def test_admin_page_and_navigation_do_not_expose_financial_links(setup):
    client,db,patch=setup
    login(client,'admin')
    response=client.get('/admin/users')
    assert response.status_code==200
    page=BeautifulSoup(response.data,'html.parser')
    assert page.select_one('a[href="/admin/users"]')
    assert not page.select_one('a[href="/risk"]')
    assert not page.select_one('.model-status')
    assert b'password_hash' not in response.data
    assert b'test-password!' not in response.data


@pytest.mark.parametrize('path',['/applications/10','/applications/10/features.csv','/api/profiles/10/score','/events/100/input'])
def test_assigned_case_access_is_allowed(setup,path):
    client,db,patch=setup
    login(client)
    endpoint=web_app.app.url_map.bind('localhost').match(path)[0]
    patch.setitem(web_app.app.view_functions,endpoint,lambda **kwargs:'allowed')
    assert client.get(path).data==b'allowed'


@pytest.mark.parametrize('path',['/applications/11','/applications/12','/applications/11/features.csv',
    '/api/profiles/11/score','/events/101/input'])
def test_unassigned_and_other_cases_are_forbidden_even_direct_urls(setup,path):
    client,db,patch=setup
    login(client)
    assert client.get(path).status_code==403


def test_analyst_cannot_reassign_batch_or_score_someone_else(setup):
    client,db,patch=setup
    csrf=login(client)
    for action,ids in [('assign',['10']),('score',['10','11'])]:
        assert client.post('/applications/batch',data={'csrf_token':csrf,'action':action,'profile_ids':ids,'assigned_user_id':'2'}).status_code==403
    assert db.queryDataset('SELECT assigned_user_id FROM demo_profiles WHERE profile_id=11').iloc[0,0]==4


def test_manager_assigns_only_real_active_analyst_accounts(setup):
    client,db,patch=setup
    csrf=login(client,'risk_manager')
    for assigned_id in ['1','3','999']:
        assert client.post('/applications/batch',data={'csrf_token':csrf,'action':'assign','profile_ids':['12'],'assigned_user_id':assigned_id}).status_code==400
    response=client.post('/applications/batch',data={'csrf_token':csrf,'action':'assign','profile_ids':['12'],'assigned_user_id':'2'})
    assert response.status_code==302
    assert db.queryDataset('SELECT assigned_user_id FROM demo_profiles WHERE profile_id=12').iloc[0,0]==2
    client.post('/logout',data={'csrf_token':csrf})
    login(client)
    patch.setitem(web_app.app.view_functions,'application_detail',lambda **kwargs:'assigned')
    assert client.get('/applications/12').data==b'assigned'


def test_case_list_is_filtered_by_user_id_not_free_text(setup):
    client,db,patch=setup
    class Data:
        def getProfiles(self,include_archived):
            return pd.DataFrame({'profile_id':[10,11,12], 'assigned_user_id':[2,4,None], 'assignee':['wrong label','analyst_test','analyst_test']})
    patch.setattr(runtime,'get_data',lambda:Data())
    patch.setitem(web_app.app.view_functions,'applications',lambda: {'ids':runtime.get_profiles()['profile_id'].tolist()})
    login(client)
    assert client.get('/applications').json['ids']==[10]


def test_analyst_cannot_forge_assignment_on_update(setup):
    client,db,patch=setup
    csrf=login(client)
    patch.setattr(runtime,'get_profile',lambda profile_id: {
        'case_label':'case','assigned_user_id':2,'assignee':'analyst_test'})
    assert client.post('/applications/10/update',data={'csrf_token':csrf,'case_label':'case','review_status':'new','assigned_user_id':'4'}).status_code==403


def test_note_author_comes_from_session_and_other_authors_are_protected(setup):
    client,db,patch=setup
    csrf=login(client)
    assert client.post('/events/100/notes',data={'csrf_token':csrf,'author':'admin','content':'new note'}).status_code==302
    assert db.queryDataset("SELECT author FROM review_notes WHERE content='new note'").iloc[0,0]=='analyst_test'
    for action in ['update','delete']:
        assert client.post(f'/notes/1001/{action}',data={'csrf_token':csrf,'content':'tamper'}).status_code==403
        assert client.post(f'/notes/1002/{action}',data={'csrf_token':csrf,'content':'tamper'}).status_code==403


@pytest.mark.parametrize('mutation', ["is_active=0", "role='admin',session_version=session_version+1", 'session_version=session_version+1'])
def test_lock_role_and_password_changes_revoke_existing_session(setup,mutation):
    client,db,patch=setup
    login(client)
    db.execute('UPDATE users SET '+mutation+' WHERE id=2')
    assert client.get('/applications').status_code==302
    assert client.get('/api/profiles/10/score').status_code==401


def test_admin_creation_and_reset_do_not_store_plaintext(setup):
    client,db,patch=setup
    csrf=login(client,'admin')
    password='new-test-password!'
    assert client.post('/admin/users',data={'csrf_token':csrf,'username':'new_analyst','full_name':'New analyst','role':'analyst','password':password}).status_code==302
    user=db.queryDataset("SELECT * FROM users WHERE username='new_analyst'").iloc[0]
    assert user.password_hash!=password
    assert client.post(f'/admin/users/{user.id}/password',data={'csrf_token':csrf,'password':'reset-password!'}).status_code==302
    assert 'reset-password!' not in str(db.queryDataset('SELECT * FROM user_audit'))


def test_admin_cannot_lock_or_demote_self_and_csrf_is_required(setup):
    client,db,patch=setup
    csrf=login(client,'admin')
    for role,active in [('analyst','1'),('admin','0')]:
        assert client.post('/admin/users/3/update',data={'csrf_token':csrf,'full_name':'Admin','role':role,'is_active':active}).status_code==400
    assert client.post('/admin/users',data={'username':'bad'}).status_code==400


def test_changed_password_invalidates_other_sessions(setup):
    client,db,patch=setup
    csrf=login(client)
    other=web_app.app.test_client()
    login(other)
    assert client.post('/account/password',data={'csrf_token':csrf,'current_password':'test-password!',
        'password':'changed-password!','confirm_password':'changed-password!'}).status_code==302
    assert other.get('/applications').status_code==302


def test_profile_helper_does_not_repeat_middleware_permission_query(setup):
    client,db,patch=setup
    login(client)
    queries=[]
    query=db.queryDataset
    def tracked(sql, params=()):
        queries.append(sql)
        return query(sql,params)
    patch.setattr(db,'queryDataset',tracked)
    class Data:
        def getProfile(self,profile_id):
            return pd.DataFrame({'profile_id':[profile_id]})
    patch.setattr(runtime,'get_data',lambda:Data())
    patch.setitem(web_app.app.view_functions,'application_detail',
                  lambda profile_id:runtime.get_profile(profile_id))
    assert client.get('/applications/10').json['profile_id']==10
    assert sum('SELECT assigned_user_id FROM demo_profiles' in sql for sql in queries)==1
