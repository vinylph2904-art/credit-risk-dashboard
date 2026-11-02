"""Data magnitude, rather than category order, controls the brand red tint."""
from web.chart_palette import RED, UNKNOWN, value_red_colors


def test_red_saturation_follows_values_and_survives_reordering():
    values = [100, 25, 75, 25]
    colors = value_red_colors(values)
    assert colors[0] == RED
    assert colors[1] == colors[3]
    assert len(set(colors)) == 3
    brightness = lambda color: sum(int(color[i:i + 2], 16) for i in [1, 3, 5])
    assert brightness(colors[0]) < brightness(colors[2]) < brightness(colors[1])
    assert value_red_colors(list(reversed(values))) == list(reversed(colors))


def test_zero_missing_and_equal_values_keep_distinct_meanings():
    assert value_red_colors([None, float('nan'), -1]) == [UNKNOWN] * 3
    assert value_red_colors([0, 0]) == ['#b9dff4'] * 2
    assert value_red_colors([5, 5]) == [RED, RED]
    assert value_red_colors([]) == []


def test_other_tabs_use_magnitude_without_recoloring_risk_groups():
    import plotly.graph_objects as go
    import json
    from bs4 import BeautifulSoup
    from web.charts import DashboardCharts

    charts = DashboardCharts()
    values = [.1, .5, .25]
    rows = [dict(label=str(i), alert_share=value, alert_n=1, n=10,
                 mean_score=value, filter_url='/risk') for i, value in enumerate(values)]
    html = charts.alertSegments(rows, 'alert_share', 'segment-risk')
    payload = json.loads(BeautifulSoup(html, 'html.parser').select_one('.chart-data').string)
    assert payload['figure']['data'][0]['marker']['color'] == value_red_colors(values)

    # A threshold group retains its meaning even if its frequency is lower.
    threshold = go.Figure(go.Bar(x=[.1, .9], y=[50, 10], marker_color=['#f2bdc3', RED]))
    charts._html(threshold, 'risk-histogram')
    assert list(threshold.data[0].marker.color) == ['#f2bdc3', RED]

    stacked = go.Figure([
        go.Bar(x=['A'], y=[10], marker_color='#dadce0'),
        go.Bar(x=['A'], y=[2], marker_color=RED),
    ])
    stacked.update_layout(barmode='stack')
    charts._html(stacked, 'comparison-chart')
    assert [trace.marker.color for trace in stacked.data] == ['#dadce0', RED]
