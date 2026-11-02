"""Reproducible UI audit using real templates and isolated, explicitly seeded data.

No preview server, production login or database writes are used. Model charts use
the saved research evaluation. Financial filters run against a six-row fixture.
"""
from collections import defaultdict
from pathlib import Path
import json
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from bs4 import BeautifulSoup
from flask import g, render_template, request
import pandas as pd
import plotly
from playwright.sync_api import sync_playwright
from auth_database import AuthDatabase
from test_financial_workspace import frame
from models.CreditRiskStatistic import CreditRiskStatistic
from web.app import app
from web import runtime, financial_context as views, request_helpers as query
from web.users import find_user

OUTPUT = ROOT / 'artifacts/workspace-audit'
OUTPUT.mkdir(parents=True, exist_ok=True)
db = AuthDatabase()
runtime.get_db = lambda: db
app.config['TESTING'] = True
reference = frame.__wrapped__().iloc[[0, 0, 0, 1, 2, 2]].reset_index(drop=True)
reference['NAME_INCOME_TYPE'] = ['Working'] * 4 + ['Pensioner'] * 2


def financial_data():
    filters = query.read_cohort_filters()
    data = CreditRiskStatistic.applyCohortFilters(reference, filters)
    dimension = request.args.get('segment', 'credit_band')
    selected = request.args.get('finance_group', '')
    if selected:
        from web.financial import segment_labels
        data = data.loc[segment_labels(data, dimension) == selected]
    return 'research', 'audit', reference, data, filters, dimension, selected


views.financial_data = financial_data
views.financial_history_context = lambda *args: (
    dict(overdue=0, debt=100, money_n=6, share=0, rate=0, overdue_n=0, dpd_n=6, outside_overdue=0),
    dict(refused_rate=0, refused_profile_rate=0, previous_n=6, previous_profile_n=6, previous_unknown_n=0))
client = app.test_client()
csrf = BeautifulSoup(client.get('/login').data, 'html.parser').select_one('[name=csrf_token]')['value']
assert client.post('/login', data=dict(username='analyst_test', password='test-password!', csrf_token=csrf)).status_code == 302


def html_for(address):
    path = urlsplit(address).path
    if path in ['/', '/risk', '/model', '/account', '/account/password']:
        response = client.get(address)
        assert response.status_code == 200, (address, response.status_code)
        return response.data.decode('utf-8')
    names = {'/applications': ('applications', 'assessment'), '/history': ('history', 'history'),
             '/diagnostics': ('portfolio_overview', 'diagnostics'), '/payments': ('payments', 'payment_analysis'),
             '/admin/users': ('users', 'users'), '/admin/audit': ('user_audit', 'user_audit')}
    template, active = names[path]
    with app.test_request_context(address):
        manager = path in ['/diagnostics', '/payments'] or request.args.get('audit_manager') == '1'
        g.current_user = find_user(db, user_id=3 if path.startswith('/admin/') else 1 if manager else 2)
        zero = defaultdict(int)
        values = dict(active=active, view='assessment' if request.args.get('view') else '',
            profiles=[], events=[], total=0, scope_total=0, queue_tabs=[], page=1, pages=1, page_size=15, start_n=0, end_n=0,
            summary=zero, work_summary=zero, workload=[], cohort_filters=query.read_cohort_filters(),
            q='', product='', income='', status='', alert='', archived=False, unassigned=False,
            sort='score', assignee='', assignees=[], score_min='', score_max='', data_check='',
            currency_options=['currency 1'], financial_currency='currency 1', credit_status='all',
            financial_filter='', version='', versions=[], days='', profile_id=None, breakdown='income',
            finance=zero, finance_focus=None, finance_groups=[], exceptions=[], loan_rows=[], selection_chips=[],
            monthly_report=defaultdict(int, states=[], transitions=[]), card_report=zero, payment_report=zero,
            history_groups=[], monthly_rows=[], latest_month=None, previous_month=None, month_difference=None,
            history_source='bureau', history_months='12', users=[], rows=[])
        if path in ['/diagnostics', '/payments']:
            values['plotly_enabled'] = True
            counts = [{'label': label, 'n': number} for label, number in [('A', 10), ('B', 50), ('C', 25)]]
            values['dpd_chart'] = runtime.charts.counts(counts, 'Số khoản', 'dpd-chart')
            values['segment_chart'] = runtime.charts.counts(counts, 'Số khoản', 'segment-chart')
            months = pd.DataFrame(dict(MONTHS_BALANCE=[-3, -2, -1], known_n=[100]*3, overdue_n=[5, 10, 7], share=[.05, .1, .07]))
            values['history_chart'] = runtime.charts.monthly(months, 'history-chart')
            values['card_chart'] = runtime.charts.utilizationBins(counts, 'card-chart')
            values['payment_chart'] = runtime.charts.paymentOutcomes([
                dict(label='Trả đủ đúng hạn', n=93), dict(label='Trả đủ sau hạn', n=7),
                dict(label='Chưa thấy trả đủ', n=3)], 'payment-chart')
            values['transition_chart'] = ''
        return render_template(template + '.html', **values)


results = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel='msedge')
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def serve(route):
        address = urlsplit(route.request.url)
        if address.path.startswith('/static/'):
            route.fulfill(path=str(ROOT / 'web' / address.path.lstrip('/')))
        elif address.path == '/vendor/plotly.min.js':
            route.fulfill(path=str(Path(plotly.__file__).parent / 'package_data/plotly.min.js'), content_type='text/javascript')
        else:
            route.fulfill(body=html_for(address.path + ('?' + address.query if address.query else '')), content_type='text/html')
    page.route('http://127.0.0.1:5000/**', serve)

    def ready():
        page.wait_for_function("[...document.querySelectorAll('.dashboard-chart')].every(n => n.classList.contains('chart-ready'))")
        page.wait_for_timeout(150)

    def check(name, width):
        page.set_viewport_size(dict(width=width, height=1000 if width > 767 else 844))
        page.evaluate('window.scrollTo(0,0)')
        page.wait_for_timeout(200)
        result = page.evaluate('''() => {
          const charts = [...document.querySelectorAll('.report-panel>.report-chart')].filter(n=>n.getBoundingClientRect().height>0);
          const legends = [...document.querySelectorAll('.chart-horizontal-legend')].filter(n=>n.getBoundingClientRect().height>0);
          const highlights = [...document.querySelectorAll('.dashboard-chart')].filter(n=>n.data && n.getBoundingClientRect().height>0).flatMap(chart =>
            chart.data.filter(t=>t.type==='bar' && !['stack','relative'].includes(chart.layout.barmode)).map(t=>({
              id:chart.id,values:Array.from(t.orientation==='h'?t.x:t.y),labels:Array.from(t.text||[]),
              rendered:[...chart.querySelectorAll('.bartext')].map(n=>n.textContent).filter(Boolean)
            })));
          const clipped = charts.flatMap(box=>[...box.querySelectorAll('.bartext')].filter(n=>n.textContent).filter(n=>{
            const a=n.getBoundingClientRect(), b=box.closest('.report-panel').getBoundingClientRect();
            return a.width>0 && (a.left<b.left-2 || a.right>b.right+2 || a.top<b.top-2 || a.bottom>b.bottom+2);
          }).map(n=>n.textContent));
          const icons = [...document.querySelectorAll('.kpi-grid .kpi')].map(card=>{
            const value=card.querySelector('strong'), badges=value.querySelectorAll('.kpi-symbol');
            if(badges.length!==1) return {valid:false};
            const badge=badges[0], rect=badge.getBoundingClientRect(), box=card.getBoundingClientRect();
            const use=badge.querySelector('use'), target=use?.getAttribute('href');
            const texts=[...value.childNodes].filter(n=>n.nodeType===3 && n.textContent.trim()).map(n=>{
              const range=document.createRange();range.selectNodeContents(n);return range.getBoundingClientRect();
            });
            return {valid:!!(target && document.querySelector(target)),
              inside:rect.right<=box.right && rect.left>=box.left,
              topLeft:rect.left-box.left<=18 && rect.top-box.top<=17,
              overlap:texts.some(text=>text.right>rect.left-3 && text.left<rect.right && text.bottom>rect.top && text.top<rect.bottom)};
          });
          return {width:innerWidth,headings:document.querySelectorAll('.topbar h1').length,
            duplicateHeading:document.querySelectorAll('.page h1').length,
            overflow:document.documentElement.scrollWidth>innerWidth,
            headerBottom:document.querySelector('.topbar').getBoundingClientRect().bottom,
            pageTop:document.querySelector('.page').getBoundingClientRect().top,
            chartHeights:charts.map(n=>n.getBoundingClientRect().height),
            titleStyles:[...document.querySelectorAll('.report-panel .panel-heading h2')].map(n=>({size:getComputedStyle(n).fontSize,
              align:getComputedStyle(n).textAlign==='start' && getComputedStyle(n).direction==='ltr'?'left':getComputedStyle(n).textAlign})),
            kpiStyles:[...document.querySelectorAll('.kpi-grid .kpi')].map(n=>({border:getComputedStyle(n).borderTopWidth,label:getComputedStyle(n.querySelector('.label')).fontSize,
              valueSize:parseFloat(getComputedStyle(n.querySelector('strong')).fontSize),background:getComputedStyle(n).backgroundColor,
              shadow:getComputedStyle(n).boxShadow,
              labelColor:getComputedStyle(n.querySelector('.label')).color,riskColor:n.querySelector('strong.financial-risk-value,strong.risk-value')?getComputedStyle(n.querySelector('strong')).color:null})),
            legendStyles:legends.flatMap(n=>[...n.querySelectorAll('button')].map(b=>({size:getComputedStyle(b).fontSize,swatch:getComputedStyle(b.querySelector('i')).width}))),
            legends:legends.map(n=>({row:getComputedStyle(n).flexDirection,wrap:getComputedStyle(n).flexWrap,overflow:n.scrollWidth>n.clientWidth})),
            sunken:[...document.querySelectorAll('.sidebar .nav-item.active,.button,.icon-button,select,textarea,.kpi-symbol,.queue-tabs a.active')].filter(n=>getComputedStyle(n).boxShadow.includes('inset')).map(n=>n.className),
            highlights,clipped,icons};
        }''')
        result['page'] = name
        assert result['headings'] == 1 and not result['duplicateHeading'], result
        assert not result['overflow'] and result['pageTop'] >= result['headerBottom'], result
        assert all(height == 200 for height in result['chartHeights']), result
        assert all(item == dict(size='14px', align='left') for item in result['titleStyles']), result
        assert all(item == dict(size='11px', swatch='12px') for item in result['legendStyles']), result
        assert all(item['border'] == '1px' and item['label'] == '12px' for item in result['kpiStyles']), result
        expected_value_size = 26 if width <= 767 else max(24, min(30, width * .019))
        assert all(abs(item['valueSize']-expected_value_size)<.1 and item['background']=='rgb(247, 248, 250)' and '-6px -6px' in item['shadow'] for item in result['kpiStyles']), result
        assert all(item['riskColor'] is None or (item['riskColor']=='rgb(207, 40, 61)' and item['labelColor']!=item['riskColor']) for item in result['kpiStyles']), result
        assert all(item == dict(row='row', wrap='wrap', overflow=False) for item in result['legends']), result
        assert not result['clipped'], result
        assert not result['sunken'], result
        assert all(item.get('valid') and item.get('inside') and item.get('topLeft') and not item.get('overlap') for item in result['icons']), result
        for item in result['highlights']:
            numbers = [value for value in item['values'] if isinstance(value, (int, float))]
            maximum = max(numbers, default=0)
            if maximum > 0:
                assert sum(bool(label) for label in item['labels']) == sum(value == maximum for value in item['values']), item
                assert all(label in item['rendered'] for label in item['labels'] if label), item
        results.append(result)
        (OUTPUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        page.screenshot(path=str(OUTPUT / f'{name}-{width}.png'), full_page=True)
        print(json.dumps(dict(page=name, width=width, charts=len(result['chartHeights']), highlights=len(result['highlights']), status='PASS')), flush=True)

    pages = [('overview', '/'), ('portfolio', '/risk'), ('assessment', '/applications?view=assessment'),
        ('queue', '/applications'), ('manager-queue', '/applications?audit_manager=1'),
        ('model', '/model'), ('history', '/history'), ('bureau', '/diagnostics'),
        ('payments', '/payments'), ('account', '/account'), ('password', '/account/password'),
        ('admin-users', '/admin/users'), ('admin-audit', '/admin/audit')]
    for name, path in pages:
        page.set_viewport_size(dict(width=1440, height=1000))
        page.goto('http://127.0.0.1:5000' + path)
        ready()
        opener = page.locator('.topbar [data-open]').first
        if opener.count():
            target = opener.get_attribute('data-open')
            opener.click()
            assert page.locator('#'+target).evaluate('(n)=>n.open')
            page.locator('#'+target+' [data-close]').click()
        legend = page.locator('.chart-horizontal-legend button').first
        if legend.count():
            legend.click()
            assert legend.get_attribute('aria-pressed') == 'false'
            legend.click()
            assert legend.get_attribute('aria-pressed') == 'true'
        if name == 'model':
            page.evaluate('window.print=()=>{window.printInvoked=true}')
            page.locator('[data-print]').click()
            assert page.evaluate('window.printInvoked')
        for width in [1440, 1024, 390]:
            check(name, width)
        if name in ['overview', 'portfolio']:
            page.set_viewport_size(dict(width=1440, height=1000))
            page.locator('#financial-ratio').select_option(index=1)
            page.wait_for_function("!document.querySelector('.page').hasAttribute('aria-busy')")
            ready()
            check(name+'-ratio', 1440)
            if name == 'portfolio':
                page.locator('#financial-dimension').select_option(index=1)
                page.wait_for_function("!document.querySelector('.page').hasAttribute('aria-busy')")
                ready()
                check(name+'-dimension', 1440)
            page.evaluate("updateDashboard(location.pathname+'?amount_max=100000')")
            page.wait_for_function("!document.querySelector('.page').hasAttribute('aria-busy')")
            ready()
            assert page.locator('.topbar .financial-scopebar b').inner_text() == '1'
            assert page.locator('[data-financial-kpi="rate"] strong').inner_text() == '100,00%'
            for width in [1440, 390]:
                check(name+'-filtered', width)
            page.evaluate("updateDashboard(location.pathname+'?amount_max=0')")
            page.wait_for_function("!document.querySelector('.page').hasAttribute('aria-busy')")
            ready()
            assert page.locator('.topbar .financial-scopebar b').inner_text() == '0'
            assert 'NaN' not in page.locator('.financial-kpis').inner_text()
            check(name+'-empty', 1440)
            # Ratio selection stays beside the one chart it changes.
            assert page.locator('.topbar #financial-ratio').count() == 0
            ratio_position = '4' if name == 'portfolio' else '5'
            assert page.locator(f'.financial-chart-grid [data-chart-position="{ratio_position}"] #financial-ratio').count() == 1
            assert page.locator('.topbar [data-open="financial-filters"]').count() == 0
    assert not errors, errors
    browser.close()
(OUTPUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'PASS: {len(results)} viewport/state checks; no browser errors.', flush=True)
