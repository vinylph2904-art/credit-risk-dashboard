"""Biểu đồ phục vụ phân tích; công thức nghiệp vụ nằm trong Models."""
import json
import math

import plotly.graph_objects as go
import plotly.io as pio
from web.chart_palette import (
    RED, MEDIUM, ROSE, LIGHT, PALE, FAINT, SURFACE, UNKNOWN, SEQUENTIAL, CATEGORICAL, value_red_colors,
)


class DashboardCharts:
    def riskHistogram(self, bins, threshold, chart_id):
        figure = go.Figure(go.Bar(
            x=[(row['low'] + row['high']) / 2 for row in bins],
            y=[row['n'] for row in bins], width=[(row['high'] - row['low']) * .95 for row in bins],
            marker_color=[RED if row['alert'] else PALE for row in bins],
            customdata=[[row['low'], row['high'], row['n'], row['share'], row['key']] for row in bins],
            hovertemplate='Điểm rủi ro: %{customdata[0]:.2%} – %{customdata[1]:.2%}'
                          '<br>%{customdata[2]:,} hồ sơ · %{customdata[3]:.1%}<extra></extra>'))
        figure.add_vrect(x0=threshold, x1=1, fillcolor=SURFACE, line_width=0, layer='below')
        figure.add_vline(x=threshold, line_color=RED, line_width=1.5, line_dash='dash')
        figure.add_annotation(x=threshold, y=1, xref='x', yref='paper',
            text=f'Ngưỡng {threshold:.2%}', showarrow=False, xanchor='left', yanchor='bottom',
            font={'size':12, 'color':RED})
        figure.update_xaxes(title='Điểm rủi ro', range=[0, 1], tickformat='.0%')
        figure.update_yaxes(title='Số hồ sơ', rangemode='tozero')
        figure.update_layout(showlegend=False, bargap=.02)
        return self._html(figure, chart_id,
            {'type':'drill', 'kind':'risk_bin', 'key':'customdata', 'index':4},
            empty_message='Chưa có hồ sơ đã chấm trong phạm vi' if not sum(row['n'] for row in bins) else None)

    def alertSegments(self, rows, metric, chart_id):
        # Both segment charts receive the same selected groups in the same order.
        rows = rows[:6]
        name = 'Tỷ lệ cảnh báo' if metric == 'alert_share' else 'Điểm rủi ro trung bình'
        figure = go.Figure(go.Bar(x=[row[metric] for row in rows], y=[row['label'] for row in rows],
            orientation='h', marker_color=value_red_colors([row[metric] for row in rows]),
            text=[f"{row[metric]:.1%}" for row in rows], textposition='outside', cliponaxis=False,
            customdata=[[row['alert_n'], row['n'], row['mean_score']] for row in rows],
            hovertemplate='%{y}<br>'+name+': %{x:.2%}<br>%{customdata[0]:,} cảnh báo / %{customdata[1]:,} đã chấm'
                          '<br>Điểm trung bình: %{customdata[2]:.2%}<extra></extra>'))
        figure.update_yaxes(autorange='reversed')
        figure.update_xaxes(title=name, tickformat='.0%', rangemode='tozero', range=[0, min(1, max([row[metric] for row in rows], default=.1)*1.3+.01)])
        urls = {row['label']: row['filter_url'] for row in rows}
        return self._html(figure, chart_id, {'type':'filter', 'key':'y', 'urls':urls},
                          empty_message='Chưa có phân khúc từ 5 hồ sơ đã chấm' if not rows else None)

    def applicationExposure(self, rows, chart_id):
        rows = rows[:6]
        figure = go.Figure()
        for name, color, alerted in [('Dưới ngưỡng', PALE, False), ('Nhóm cảnh báo', RED, True)]:
            values = [row['alerted_credit'] if alerted else
                      row['credit']-row['alerted_credit'] if row['credit'] is not None else None for row in rows]
            figure.add_trace(go.Bar(x=values, y=[row['label'] for row in rows], orientation='h', name=name,
                marker_color=color, hovertemplate='%{y}<br>%{fullData.name}: %{x:,.0f}<extra></extra>'))
        figure.update_layout(barmode='stack')
        figure.update_yaxes(autorange='reversed')
        figure.update_xaxes(title='Giá trị khoản vay · đơn vị nguồn', rangemode='tozero')
        return self._html(figure, chart_id,
            {'type':'filter', 'key':'y', 'urls':{row['label']:row['filter_url'] for row in rows}},
            empty_message='Chưa có phân khúc đủ dữ liệu' if not rows else None)

    def riskConcentration(self, rows, chart_id):
        known = [row for row in rows if row['alerted_credit'] is not None]
        figure = go.Figure(go.Scatter(
            x=[row['alert_share'] for row in known], y=[row['alerted_credit'] for row in known],
            mode='markers+text', text=[row['label'] for row in known], textposition='top center',
            marker={'size':[row['n'] for row in known], 'sizemode':'area',
                    'sizeref':2*max([row['n'] for row in known], default=1)/(44**2),
                    'sizemin':7, 'color':value_red_colors([row['alert_share'] for row in known]), 'line':{'width':1,'color':'white'}},
            customdata=[[row['filter_url'],row['n'],row['credit']] for row in known],
            hovertemplate='%{text}<br>Tỷ lệ cảnh báo: %{x:.2%}<br>Tiền cảnh báo: %{y:,.0f}'
                          '<br>%{customdata[1]} hồ sơ · tổng tiền: %{customdata[2]:,.0f}<extra></extra>'))
        figure.update_xaxes(title='Tỷ lệ cảnh báo',tickformat='.0%',rangemode='tozero',
            range=[0,min(1,max([row['alert_share'] for row in known],default=.1)*1.25+.02)])
        figure.update_yaxes(title='Tiền cảnh báo · đơn vị nguồn',rangemode='tozero')
        figure.update_layout(showlegend=False)
        return self._html(figure,chart_id,{'type':'filter','key':'text',
            'urls':{row['label']:row['filter_url'] for row in known}},
            empty_message='Chưa có nhóm đủ thông tin tiền' if not known else None)

    def creditSplit(self, amounts, chart_id, normal_url, alert_url):
        figure = go.Figure()
        total = amounts['total_amount']
        if amounts['eligible_n']:
            for name,value,color,url in [
                ('Dưới ngưỡng',total-amounts['alert_amount'],PALE,normal_url),
                ('Nhóm cảnh báo',amounts['alert_amount'],RED,alert_url)]:
                figure.add_trace(go.Bar(x=[value],y=['Đã chấm'],orientation='h',name=name,
                    marker_color=color,customdata=[[url,value/total if total else None]],
                    hovertemplate='%{fullData.name}<br>%{x:,.0f} · %{customdata[1]:.1%}<extra></extra>'))
        figure.update_layout(barmode='stack',bargap=.55)
        figure.update_yaxes(visible=False)
        figure.update_xaxes(rangemode='tozero',title=None)
        return self._html(figure,chart_id,{'type':'profile'},height=120,
            empty_message='Chưa có hồ sơ đã chấm đủ thông tin tiền' if not amounts['eligible_n'] else None)

    def _html(self, figure, chart_id, interaction=None, height=330, empty_message=None):
        figure.update_layout(
            template='plotly_white', height=height, dragmode=False,
            font={'family': 'Inter, Segoe UI, Arial, sans-serif', 'size': 12, 'color': '#6b7e8f'},
            separators=',.',
            margin={'l': 18, 'r': 24, 't': 24, 'b': 42},
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            colorway=CATEGORICAL,
            hoverlabel={'bgcolor': '#ffffff', 'bordercolor': '#dce8f1', 'align': 'left',
                        'font': {'family': 'Inter, Segoe UI, Arial, sans-serif', 'size': 13, 'color': '#263849'},
                        'namelength': -1},
            hoverdistance=24, barcornerradius=6,
            legend={'orientation': 'h', 'y': 1.14, 'x': 0, 'title_text': ''},
        )
        figure.update_xaxes(fixedrange=True, showgrid=False, zeroline=False, automargin=True)
        figure.update_yaxes(fixedrange=True, gridcolor='#dfe9f1', zeroline=False, automargin=True)
        # Nhãn chuỗi nằm cùng tooltip, tránh hộp màu phụ bị dính bên cạnh.
        for trace in figure.data:
            if trace.type in ['bar', 'pie']:
                trace.marker.line = {'color': 'rgba(255,255,255,.8)', 'width': 0 if chart_id.startswith('finance-') else 1}
                trace.textfont.size = 12
            if trace.type == 'bar' and trace.text is None and trace.texttemplate is None:
                horizontal = trace.orientation == 'h'
                values = list(trace.x if horizontal else trace.y)
                axis_ref = (trace.xaxis or 'x') if horizontal else (trace.yaxis or 'y')
                axis = figure.layout[axis_ref[0] + 'axis' + axis_ref[1:]]
                percent = '%' in (axis.tickformat or '')
                stacked = figure.layout.barmode in ['stack', 'relative']
                if len(values) <= 16:
                    trace.text = [None if value is None or not math.isfinite(value) or (stacked and percent and value < .06)
                                  else f'{value:.1%}'.replace('.', ',') if percent
                                  else f'{value:,.0f}'.replace(',', '.') for value in values]
                    if '~s' in (axis.tickformat or ''):
                        trace.texttemplate = '%{x:.3~s}' if horizontal else '%{y:.3~s}'
                    trace.textposition = 'inside' if stacked else 'outside'
                    trace.textfont = {'size': 12}
                    trace.cliponaxis = False
                    if not stacked:
                        maximum = max((value for value in values if value is not None and math.isfinite(value)), default=0)
                        if maximum > 0 and axis.range is None:
                            axis.range = [0, maximum * 1.18]
            if trace.type == 'pie':
                if trace.hole is None:
                    trace.hole = .52
                trace.textinfo = trace.textinfo or 'percent'
                trace.textfont.size = 12
            template = getattr(trace, 'hovertemplate', None)
            if template and '<extra>%{fullData.name}</extra>' in template:
                main = template.split('<extra>')[0]
                prefix = '' if '%{fullData.name}' in main else '<b>%{fullData.name}</b><br>'
                trace.hovertemplate = prefix + template.replace('<extra>%{fullData.name}</extra>', '<extra></extra>')
        if chart_id.startswith('finance-'):
            figure.update_layout(font_color='#6b7e8f', paper_bgcolor='rgba(255,255,255,0)', plot_bgcolor='rgba(255,255,255,0)',
                hoverlabel={'bgcolor': '#ffffff', 'bordercolor': '#dce8f1', 'font_color': '#263849'})
            figure.update_xaxes(showgrid=True, gridcolor='#dfe9f1', gridwidth=1, showline=False, zeroline=False, ticks='',
                tickfont_color='#6b7e8f', title_font_color='#6b7e8f')
            figure.update_yaxes(showgrid=False, gridcolor='#dfe9f1', showline=False, zeroline=False, ticks='',
                tickfont_color='#6b7e8f', title_font_color='#6b7e8f')
        if empty_message:
            figure.add_annotation(text=empty_message, x=0.5, y=0.5, xref='paper', yref='paper',
                                  showarrow=False, font={'color': '#6b7e8f', 'size': 16})
        payload = {'figure': json.loads(pio.to_json(figure)), 'interaction': interaction}
        encoded = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
        return f'<div class="dashboard-chart" id="{chart_id}"></div><script type="application/json" class="chart-data" data-chart="{chart_id}">{encoded}</script>'

    def counts(self, rows, unit, chart_id):
        # So sánh các mức quá hạn; nhóm không quá hạn vẫn có nút/số đếm riêng.
        rows = [row for row in rows if row['label'] != 'Không quá hạn']
        colors = {'1–30 ngày': LIGHT, '31–60 ngày': ROSE,
                  '61–90 ngày': MEDIUM, 'Trên 90 ngày': RED, 'Chưa xác định': UNKNOWN}
        figure = go.Figure(go.Bar(
            x=[row['n'] for row in rows], y=[row['label'] for row in rows], orientation='h',
            marker_color=[colors.get(row['label'], UNKNOWN) for row in rows], text=[row['n'] for row in rows],
            textposition='outside', cliponaxis=False,
            hovertemplate='%{y}<br>%{x:,} ' + unit + '<extra></extra>',
        ))
        figure.update_yaxes(autorange='reversed')
        figure.update_xaxes(title=unit, rangemode='tozero', dtick=1 if max((row['n'] for row in rows), default=0) < 10 else None)
        return self._html(figure, chart_id, {'type': 'drill', 'kind': 'dpd', 'key': 'y'},
                          empty_message='Không có khoản trong các nhóm này' if not sum(row['n'] for row in rows) else None)

    def segmentComparison(self, groups, total_debt, total_overdue, chart_id):
        labels = [row['label'] for row in groups]
        debt_shares = [row['debt'] / total_debt if total_debt and row['debt'] is not None else None for row in groups]
        overdue_shares = [row['overdue'] / total_overdue if total_overdue and row['overdue'] is not None else None for row in groups]
        custom = [[row['debt'], row['overdue'], row['money_n']] for row in groups]
        figure = go.Figure()
        for name, shares, color in [('Tỷ trọng dư nợ', debt_shares, PALE),
                                    ('Tỷ trọng tiền quá hạn', overdue_shares, RED)]:
            figure.add_trace(go.Bar(x=shares, y=labels, orientation='h', name=name,
                marker_color=color, customdata=custom,
                hovertemplate='%{y}<br>%{fullData.name}: %{x:.1%}<br>Dư nợ: %{customdata[0]:,.0f}'
                              '<br>Tiền quá hạn: %{customdata[1]:,.0f}<br>%{customdata[2]:,} khoản đủ tiền<extra></extra>'))
        figure.update_layout(barmode='group')
        figure.update_xaxes(tickformat='.0%', rangemode='tozero')
        figure.update_yaxes(autorange='reversed')
        urls = {row['label']: row['filter_url'] for row in groups if row.get('filter_url')}
        return self._html(figure, chart_id, {'type': 'filter', 'key': 'y', 'urls': urls},
                          empty_message='Chưa có dư nợ hợp lệ để so sánh' if not total_debt else None)

    def workStatus(self, rows, chart_id):
        figure = go.Figure()
        total = sum(row['n'] for row in rows)
        for row, color in zip(rows, [LIGHT, MEDIUM, FAINT]):
            figure.add_trace(go.Bar(x=[row['n'] / total if total else 0], y=['Hồ sơ'],
                orientation='h', name=f"{row['label']} · {row['n']:,}", marker_color=color,
                customdata=[[row['url']]],
                hovertemplate='%{fullData.name}<br>%{x:.1%}<extra></extra>'))
        figure.update_layout(barmode='stack')
        figure.update_xaxes(range=[0, 1], tickformat='.0%')
        figure.update_yaxes(visible=False)
        return self._html(figure, chart_id, {'type': 'profile'}, height=160)

    def monthly(self, monthly, chart_id):
        data = monthly.set_index('MONTHS_BALANCE')
        if not data.empty:
            data = data.reindex(range(int(data.index.min()), int(data.index.max()) + 1))
        figure = go.Figure()
        figure.add_trace(go.Scatter(x=data.index.tolist(), y=data['share'].tolist(),
            mode='lines+markers', name='Tỷ lệ quá hạn', line={'color': RED, 'width': 3},
            yaxis='y', zorder=1,
            customdata=data[['known_n', 'overdue_n']].values.tolist(), connectgaps=False,
            hovertemplate='Tháng %{x}<br>Quá hạn: %{y:.2%}<br>%{customdata[1]:,} / %{customdata[0]:,} khoản<extra></extra>'))
        figure.add_trace(go.Bar(x=data.index.tolist(), y=data['known_n'].tolist(), name='Khoản có trạng thái',
            marker_color=LIGHT, yaxis='y2', zorder=0,
            hovertemplate='Tháng %{x}<br>%{y:,} khoản có trạng thái<extra></extra>'))
        figure.update_layout(showlegend=True, bargap=.4,
            yaxis={'title': 'Tỷ lệ quá hạn (%)', 'tickformat': '.1%', 'rangemode': 'tozero', 'side': 'left'},
            yaxis2={'title': 'Số khoản có trạng thái', 'tickformat': ',.0f', 'rangemode': 'tozero',
                    'overlaying': 'y', 'side': 'right', 'showgrid': False})
        figure.update_xaxes(title_text='Tháng tương đối trước mốc nộp đơn', dtick=1)
        return self._html(figure, chart_id, {'type': 'drill', 'kind': 'month', 'key': 'x'},
                          empty_message='Không có lịch sử trong phạm vi' if data.empty else None)

    def paymentOutcomes(self, rows, chart_id):
        colors = {'Trả đủ đúng hạn': PALE, 'Trả đủ sau hạn': RED, 'Chưa thấy trả đủ': MEDIUM}
        figure = go.Figure(go.Pie(labels=[row['label'] for row in rows], values=[row['n'] for row in rows],
            hole=0.65, sort=False, marker_colors=[colors[row['label']] for row in rows],
            textinfo='percent', textposition='inside',
            hovertemplate='%{label}<br>%{value:,} kỳ · %{percent}<extra></extra>'))
        return self._html(figure, chart_id, {'type': 'drill', 'kind': 'payment', 'key': 'label'},
                          empty_message='Không có kỳ trả hợp lệ' if not sum(row['n'] for row in rows) else None)

    def utilizationBins(self, rows, chart_id):
        figure = go.Figure(go.Bar(x=[row['label'] for row in rows], y=[row['n'] for row in rows],
            marker_color=SEQUENTIAL,
            text=[row['n'] for row in rows], textposition='outside', cliponaxis=False,
            hovertemplate='%{x}<br>%{y:,} thẻ<extra></extra>'))
        figure.update_xaxes(type='category', title='Mức sử dụng hạn mức')
        figure.update_yaxes(title='Số thẻ', rangemode='tozero')
        figure.update_layout(bargap=0.08)
        return self._html(figure, chart_id, {'type': 'drill', 'kind': 'card', 'key': 'x'},
                          empty_message='Không có thẻ đủ dữ liệu' if not sum(row['n'] for row in rows) else None)

    def scores(self, distribution, threshold, chart_id):
        figure = go.Figure(go.Bar(x=[row['label'] for row in distribution], y=[row['n'] for row in distribution],
            marker_color=[RED if row['above_threshold'] else PALE for row in distribution],
            text=[row['n'] for row in distribution], textposition='outside', cliponaxis=False,
            hovertemplate='%{x}<br>%{y:,} hồ sơ<extra></extra>'))
        figure.update_xaxes(type='category', title=f'Khoảng điểm · ngưỡng {threshold:.2%}')
        figure.update_yaxes(title='Số hồ sơ', rangemode='tozero')
        return self._html(figure, chart_id, {'type': 'drill', 'kind': 'score', 'key': 'x'},
                          empty_message='Không có hồ sơ đã chấm' if not sum(row['n'] for row in distribution) else None)

    def riskSegments(self, rows, baseline, chart_id):
        figure = go.Figure(go.Scatter(x=[row['alert_share'] for row in rows], y=[row['label'] for row in rows],
            mode='markers', marker={'size': 14, 'color': value_red_colors([row['alert_share'] for row in rows])},
            customdata=[[row['alert_n'], row['n'], row['pending_alert_n']] for row in rows],
            hovertemplate='%{y}<br>Cảnh báo: %{x:.1%}<br>%{customdata[0]} / %{customdata[1]} đã chấm'
                          '<br>%{customdata[2]} cảnh báo chưa rà soát<extra></extra>'))
        if baseline is not None:
            figure.add_vline(x=baseline, line_dash='dot', line_color='#888888')
        figure.update_xaxes(tickformat='.0%', rangemode='tozero', title='Tỷ lệ hồ sơ có cảnh báo')
        figure.update_yaxes(autorange='reversed')
        urls = {row['label']: row['filter_url'] for row in rows if row.get('filter_url')}
        return self._html(figure, chart_id, {'type': 'filter', 'key': 'y', 'urls': urls},
                          empty_message='Không có nhóm đủ 5 hồ sơ đã chấm' if not rows else None)

    def utilizationScore(self, data, threshold, chart_id):
        figure = go.Figure(go.Scatter(x=data['utilization'].tolist(), y=data['score'].tolist(), mode='markers',
            customdata=data[['detail_url']].values.tolist(),
            marker={'size': 9, 'color': [RED if flag == 1 else PALE for flag in data['alert']]},
            hovertemplate='Utilization: %{x:.1%}<br>Điểm dự báo: %{y:.1%}<extra></extra>'))
        figure.add_hline(y=threshold, line_dash='dot', line_color=RED)
        figure.update_xaxes(tickformat='.0%', title='Utilization trung vị / hồ sơ', rangemode='tozero')
        figure.update_yaxes(tickformat='.0%', title='Điểm dự báo', range=[0, 1])
        return self._html(figure, chart_id, {'type': 'profile'},
                          empty_message='Không có hồ sơ đủ cả hai thông tin' if data.empty else None)

    def transitions(self, report, chart_id):
        states = report['states']
        shares = [[cell['share'] for cell in row['cells']] for row in report['transitions']]
        counts = [[cell['n'] for cell in row['cells']] for row in report['transitions']]
        figure = go.Figure(go.Heatmap(x=states, y=states, z=shares, customdata=counts,
            zmin=0, zmax=1, colorscale=[[0, FAINT], [.35, LIGHT], [.7, MEDIUM], [1, RED]], texttemplate='%{z:.0%}',
            colorbar={'tickformat': '.0%'},
            hovertemplate='%{y} → %{x}<br>%{customdata:,} cặp · %{z:.1%}<extra></extra>'))
        figure.update_xaxes(type='category', title='Trạng thái tháng t+1')
        figure.update_yaxes(type='category', title='Trạng thái tháng t', autorange='reversed')
        return self._html(figure, chart_id, {'type': 'drill', 'kind': 'transition'},
                          empty_message='Không có cặp tháng liên tiếp hợp lệ' if not report['pair_n'] else None)

