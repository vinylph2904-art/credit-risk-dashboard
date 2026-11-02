"""Queue counts and navigation must preserve the user's working scope."""
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from flask import g
import pandas as pd
import pytest

from auth_database import AuthDatabase
from web.app import app
from web import application_routes as routes, runtime
from web.users import find_user


@pytest.fixture
def queue_page(monkeypatch):
    db = AuthDatabase()
    data = pd.DataFrame({
        'profile_id': [10, 11, 12, 13], 'source_application_id': [100, 101, 102, 103],
        'case_label': ['Case A', 'Case B', 'Case C', 'Other'],
        'score': [.8, .2, None, .6], 'alert': [1, 0, None, 1],
        'review_status': ['new', 'reviewed', 'in_review', 'reviewed'],
        'assignee': ['analyst_test', '', '', 'analyst_test'],
        'AMT_CREDIT': [100, 200, 300, 400], 'is_archived': [0] * 4,
        'NAME_CONTRACT_TYPE': ['Cash loans'] * 4,
    })
    monkeypatch.setattr(runtime, 'get_db', lambda: db)
    monkeypatch.setattr(runtime, 'get_profiles', lambda *args: data.copy())
    monkeypatch.setattr(routes.portfolio_views, 'portfolio_context', lambda **kwargs: {
        'profiles': data.copy(), 'cohort_filters': dict(product='', income='', availability='',
            amount_min=None, amount_max=None, age_min=None, age_max=None),
        'work_summary': {}, 'workload': [], 'financial_currency': 'currency 1',
        'currency_options': ['currency 1'], 'credit_status': 'Active', 'financial_filter': '',
    })

    def render(address):
        with app.test_request_context(address):
            g.current_user = find_user(db, user_id=1)
            return BeautifulSoup(routes.applications(), 'html.parser')
    yield render
    db.conn.close()


def test_filter_chips_remove_one_filter_and_preserve_working_scope(queue_page):
    page = queue_page('/applications?q=Case&alert=1&page=9&page_size=15')
    assert page.select('.assessment-queues a') == []
    assert len(page.select('.queue-tabs a')) == 3
    assert 'Hàng đợi' in page.select_one('.queue-tabs a.active').text
    assert '1 hồ sơ phù hợp' in page.select_one('.assessment-count').get_text(' ', strip=True)
    assert '/ 4 hồ sơ' in page.select_one('.assessment-count').get_text(' ', strip=True)
    alert_chip = next(chip for chip in page.select('.assessment-filter-chip') if 'Có cảnh báo' in chip.text)
    args = parse_qs(urlsplit(alert_chip['href']).query)
    assert args['q'] == ['Case'] and args['page_size'] == ['15']
    assert 'alert' not in args and 'page' not in args


def test_assignment_tab_has_its_own_content_and_active_state(queue_page):
    page = queue_page('/applications?section=assignments&view=assessment')
    assert 'Phân công' in page.select_one('.queue-tabs a.active').text
    assert page.select_one('.workload-panel')
    assert page.select_one('.assessment-table-panel') is None
    assert page.select_one('.assessment-search') is None


def test_score_fields_show_percent_without_changing_existing_query_units(queue_page):
    page = queue_page('/applications?score_min=0.15&score_max=0.8')
    assert float(page.select_one('#filter-score-min')['value']) == 15
    assert float(page.select_one('#filter-score-max')['value']) == 80
    assert page.select_one('input[name="score_min"]')['value'] == '0.15'
    assert '15,00%' in page.select_one('.assessment-active-filters').text


def test_empty_queue_and_external_page_size_form_are_valid(queue_page):
    page = queue_page('/applications?q=missing&status=pending')
    assert '0 hồ sơ phù hợp' in page.select_one('.assessment-count').text
    assert '0–0' in page.select_one('.assessment-count').text
    assert len(page.select('.profile-table th')) == 6
    assert page.select_one('#assessment-page-size').find_parent('form') is None
    assert page.select_one('#page-size')['form'] == 'assessment-page-size'
    assert page.select_one('#application-search').find_parent('dialog') is None
    assert page.select_one('.profile-table td')['colspan'] == '6'


def test_each_profile_has_one_review_action(queue_page):
    page = queue_page('/applications')
    rows = page.select('.profile-table tbody tr')
    assert len(rows) == 4
    assert all(len(row.select('td')) == 6 for row in rows)
    assert all(len(row.select('a.profile-link[data-assessment-detail]')) == 1 for row in rows)
    assert page.select_one('.financial-topbar-controls .assessment-actions [data-open="import-profiles"]')
    assert page.select_one('.assessment-toolbar [data-open="application-filters"]')
    assert page.select_one('.assessment-toolbar').find_parent('header') is not None
    assert page.select_one('.assessment-navigation-row .queue-tabs')
    assert page.select_one('.assessment-navigation-row .assessment-threshold')
    assert 'financial-view' in page.body['class']
