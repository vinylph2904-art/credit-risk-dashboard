"""Presentation aggregates must retain scoring boundaries and valid denominators."""
import numpy as np
import pandas as pd
import pytest

from web.analytics import (filter_score_range, ordered_segments, pending_priority,
                           risk_bins, segment_report, segment_values)


def test_histogram_threshold_and_endpoints_reconcile():
    threshold = .16238802555994059
    scores = pd.Series([0, .05, .1, np.nextafter(threshold, 0), threshold,
                        np.nextafter(threshold, 1), .25, .5, 1.0, np.nan])
    bins = risk_bins(scores, threshold)
    assert sum(row['n'] for row in bins) == int(scores.notna().sum())
    assert sum(row['n'] for row in bins if row['alert']) == int(scores.ge(threshold).sum())
    assert sum(row['share'] for row in bins) == pytest.approx(1)
    frame = pd.DataFrame({'score': scores})
    for row in bins:
        selected = filter_score_range(frame, *row['key'].split(':'))
        assert len(selected) == row['n']


@pytest.mark.parametrize('low,high', [('nan','1'), ('0','inf'), ('-.1','.5'), ('.7','.2'), ('0','1.1')])
def test_invalid_score_ranges_rejected(low, high):
    with pytest.raises(ValueError):
        filter_score_range(pd.DataFrame({'score':[.1]}), low, high)


def test_segments_use_scored_profiles_and_valid_credit_only():
    data = pd.DataFrame({
        'score':[.1,.3,np.nan,.2], 'alert':[0,1,np.nan,1],
        'AMT_CREDIT':[100,200,99999,np.inf],
        'NAME_CONTRACT_TYPE':['Cash loans']*3+['Revolving loans']})
    rows = {row['label']:row for row in segment_report(data, 'product')}
    cash = rows['Vay tiền mặt']
    assert cash['n'] == 2 and cash['alert_n'] == 1
    assert cash['alert_share'] == .5
    assert cash['mean_score'] == pytest.approx(.2)
    assert cash['credit'] == 300 and cash['alerted_credit'] == 200
    other = rows['Vay quay vòng']
    assert other['credit'] is None and other['alerted_credit'] is None
    assert other['excluded_credit_n'] == 1


def test_display_bands_boundaries_and_missing():
    data = pd.DataFrame({'AMT_CREDIT':[0,249999,250000,500000,1000000,np.nan,-1],
                         'AGE_YEARS':[29,30,39,40,60,np.nan,-1]})
    assert segment_values(data,'credit_band').tolist() == [
        'Dưới 250.000','Dưới 250.000','250.000–<500.000','500.000–<1.000.000',
        'Từ 1.000.000','Chưa có thông tin','Chưa có thông tin']
    assert segment_values(data,'age_band').iloc[1] == '30–39'


def test_priority_is_only_unfinished_alerts_and_has_stable_tie_break():
    data = pd.DataFrame({'score':[.8,.8,.99,.9,np.nan,.7], 'alert':[1,1,1,0,1,1],
        'review_status':['in_review','new','reviewed','new','new','new'],
        'source_application_id':[20,10,30,40,50,60]})
    assert pending_priority(data)['source_application_id'].tolist() == [10,20,60]
    assert pending_priority(data,limit=2)['source_application_id'].tolist() == [10,20]


def test_amount_shares_distinguish_group_denominator_and_portfolio_denominator():
    data = pd.DataFrame({'score':[.3,.1,.4,.1,.2], 'alert':[1,0,1,0,1],
        'AMT_CREDIT':[100,900,300,0,np.nan], 'NAME_CONTRACT_TYPE':['A','A','B','C','D']})
    rows={row['label']:row for row in segment_report(data,'product')}
    assert rows['A']['alerted_amount_share'] == .1
    assert rows['A']['alerted_contribution'] == .25
    assert rows['B']['alerted_amount_share'] == 1
    assert rows['B']['alerted_contribution'] == .75
    assert rows['C']['alerted_amount_share'] is None
    assert rows['C']['alerted_contribution'] == 0
    assert rows['D']['alerted_amount_share'] is None
    assert rows['D']['alerted_contribution'] is None
    assert sum(row['alerted_contribution'] or 0 for row in rows.values()) == 1
    data['alert']=0
    assert all(row['alerted_contribution'] is None for row in segment_report(data,'product'))


def test_segment_sort_keeps_missing_last_in_both_directions():
    rows=[{'label':'A','n':1,'credit':None},{'label':'B','n':2,'credit':0},
          {'label':'C','n':3,'credit':100},{'label':'D','n':4,'credit':np.nan}]
    assert [row['label'] for row in ordered_segments(rows,'credit')][:2] == ['C','B']
    assert [row['label'] for row in ordered_segments(rows,'credit',False)][:2] == ['B','C']
    with pytest.raises(ValueError):
        ordered_segments(rows,'unsupported')


def test_paired_segment_charts_keep_same_groups_and_order():
    import json
    from bs4 import BeautifulSoup
    from web.charts import DashboardCharts
    rows=[{'label':label,'n':10,'alert_n':n,'mean_score':.2,'alert_share':n/10,
           'credit':credit,'alerted_credit':credit/2,'filter_url':'/risk?segment='+label}
          for label,n,credit in [('A',1,900),('B',9,100),('C',3,400)]]
    def payload(html):
        return json.loads(BeautifulSoup(html,'html.parser').select_one('.chart-data').string)
    charts=DashboardCharts()
    for field in ['alert_share','credit','alerted_credit']:
        ordered=ordered_segments(rows,field)
        left=payload(charts.alertSegments(ordered,'alert_share','left'))
        right=payload(charts.applicationExposure(ordered,'right'))
        matrix=payload(charts.riskConcentration(ordered,'matrix'))
        expected=[row['label'] for row in ordered]
        assert left['figure']['data'][0]['y'] == expected
        assert all(trace['y']==expected for trace in right['figure']['data'])
        assert matrix['figure']['data'][0]['text'] == expected
