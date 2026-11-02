"""Visualize frozen historical predictions; never fit or change the model."""
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from sklearn.calibration import calibration_curve
from sklearn.metrics import precision_recall_curve, roc_curve

from web.charts import DashboardCharts
from web.chart_palette import (
    BLUE, BLUE_DEEP, RED, ROSE, LIGHT, FAINT,
)


def sample_indices(length):
    return np.unique(np.linspace(0, length - 1, min(length, 350)).astype(int))


def curve(x, y, x_title, y_title):
    indices = sample_indices(len(x))
    figure = go.Figure(go.Scatter(x=np.asarray(x)[indices], y=np.asarray(y)[indices],
        mode='lines', line={'color':RED,'width':2}, showlegend=False))
    figure.update_xaxes(title=x_title, tickformat='.0%', range=[0, 1])
    figure.update_yaxes(title=y_title, tickformat='.0%', range=[0, 1])
    return figure


def ranking_capacity(predictions):
    """Describe frozen scores at a review budget; never choose a new policy."""
    ranked = predictions.sort_values(['score', 'SK_ID_CURR'], ascending=[False, True], kind='stable')
    positive_n = int(ranked['TARGET'].sum())
    n = len(ranked)
    prevalence = positive_n / n
    cumulative = ranked['TARGET'].cumsum().to_numpy()
    rows = []
    for fraction in [.05, .10, .20]:
        review_n = int(np.ceil(fraction * n))
        captured = int(cumulative[review_n - 1])
        precision = captured / review_n
        rows.append({'fraction': fraction, 'review_n': review_n, 'captured_n': captured,
                     'precision': precision, 'recall': captured / positive_n,
                     'lift': precision / prevalence})
    figure = curve(np.r_[0, np.arange(1, n + 1) / n], np.r_[0, cumulative / positive_n],
                   'Tỷ lệ hồ sơ được rà soát', 'Tỷ lệ ca TARGET = 1 được phát hiện')
    figure.data[0].name = 'Xếp theo score'
    figure.data[0].hovertemplate = 'Rà soát: %{x:.2%}<br>Phát hiện: %{y:.2%}<extra></extra>'
    figure.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode='lines', name='Thứ tự ngẫu nhiên · kỳ vọng',
                               line={'color': LIGHT, 'dash': 'dot'}, showlegend=True,
                               hovertemplate='Rà soát: %{x:.2%}<br>Kỳ vọng: %{y:.2%}<extra></extra>'))
    figure.add_trace(go.Scatter(x=[row['review_n'] / n for row in rows],
                               y=[row['recall'] for row in rows], mode='markers',
                               marker={'color': RED, 'size': 8}, showlegend=False,
                               customdata=[[row['review_n'], row['captured_n'], row['precision']] for row in rows],
                               hovertemplate='%{customdata[0]:,} hồ sơ · %{customdata[1]:,} ca<br>'
                                             'Precision: %{customdata[2]:.2%}<br>Recall: %{y:.2%}<extra></extra>'))
    figure.update_layout(showlegend=True)
    figure.data[0].showlegend = True
    return rows, figure


@lru_cache(maxsize=2)
def historical_charts(root, threshold, report_folder='reports/modeling', dataset='test',
                      predictions_file=None, metrics_file=None, policy=None, candidates_file=None):
    folder = Path(root) / report_folder
    if dataset == 'validation':
        defaults = ('validation_predictions.parquet', 'validation_comparison.csv',
                    'CatBoost_selected_5_to_1', 'validation_threshold_candidates.csv')
    else:
        defaults = ('04_test_predictions.parquet', '04_test_metrics.csv',
                    'chosen_5_to_1', '04_validation_threshold_candidates.csv')
    predictions = pd.read_parquet(folder / (predictions_file or defaults[0]))
    metrics = pd.read_csv(folder / (metrics_file or defaults[1]))
    main = metrics.loc[metrics['policy'] == (policy or defaults[2])].iloc[0]
    candidates_path = folder / (candidates_file or defaults[3])
    if not np.isclose(main['threshold'], threshold, rtol=0, atol=1e-12):
        raise ValueError('Ngưỡng trong báo cáo khác model đang triển khai.')
    charts, result = DashboardCharts(), {}
    fpr, tpr, _ = roc_curve(predictions['TARGET'], predictions['score'])
    figure = curve(fpr, tpr, 'False positive rate', 'True positive rate')
    figure.add_shape(type='line', x0=0, y0=0, x1=1, y1=1, line={'color':'#d4dce5','dash':'dot'})
    figure.add_trace(go.Scatter(x=[float(main['fp']/(main['fp']+main['tn']))],y=[float(main['recall'])],
        mode='markers',marker={'color':RED,'size':8},showlegend=False,
        hovertemplate=f'Ngưỡng {threshold:.2%}<br>FPR: %{{x:.2%}}<br>Recall: %{{y:.2%}}<extra></extra>'))
    result['roc'] = charts._html(figure, 'evaluation-roc')
    precision, recall, _ = precision_recall_curve(predictions['TARGET'], predictions['score'])
    figure = curve(recall, precision, 'Recall', 'Precision')
    figure.add_hline(y=float(predictions['TARGET'].mean()), line_color='#c2ccd7', line_dash='dot')
    figure.add_trace(go.Scatter(x=[float(main['recall'])],y=[float(main['precision'])],
        mode='markers',marker={'color':RED,'size':8},showlegend=False,
        hovertemplate=f'Ngưỡng {threshold:.2%}<br>Recall: %{{x:.2%}}<br>Precision: %{{y:.2%}}<extra></extra>'))
    result['pr'] = charts._html(figure, 'evaluation-pr')
    matrix = [[int(main['tn']), int(main['fp'])], [int(main['fn']), int(main['tp'])]]
    figure = go.Figure(go.Heatmap(z=matrix, x=['Dưới ngưỡng', 'Cảnh báo'],
        y=['Không ghi nhận khó khăn', 'Có khó khăn thanh toán'],
        text=[[f'{n:,}' for n in row] for row in matrix], texttemplate='%{text}',
        colorscale=[[0, FAINT], [.4, LIGHT], [.75, BLUE], [1, BLUE_DEEP]], showscale=False,
        hovertemplate='%{y} · %{x}<br>%{z:,} hồ sơ<extra></extra>'))
    figure.update_yaxes(autorange='reversed')
    figure.update_layout(showlegend=False)
    result['confusion'] = charts._html(figure, 'evaluation-confusion')
    observed, predicted = calibration_curve(predictions['TARGET'], predictions['score'], n_bins=10, strategy='quantile')
    figure = curve(predicted, observed, 'Điểm trung bình', 'Tỷ lệ khó khăn thanh toán')
    figure.update_traces(mode='lines+markers', marker={'size':5},
                         hovertemplate='Điểm: %{x:.2%}<br>Khó khăn thanh toán: %{y:.2%}<extra></extra>')
    limit = max(float(max(predicted)), float(max(observed))) * 1.1
    figure.add_shape(type='line', x0=0, y0=0, x1=limit, y1=limit, line={'color':'#c5ced9','dash':'dot'})
    figure.update_xaxes(range=[0, limit]); figure.update_yaxes(range=[0, limit])
    result['calibration'] = charts._html(figure, 'evaluation-calibration')
    candidates = pd.read_csv(candidates_path).sort_values('threshold')
    candidates = candidates.iloc[sample_indices(len(candidates))]
    figure = go.Figure()
    candidates['precision'] = candidates['tp'].div(candidates['tp']+candidates['fp']).where(candidates['tp']+candidates['fp']>0)
    for column, name, color, dash in [('precision','Precision',BLUE,'solid'),
            ('recall','Recall',RED,'dash'), ('alert_rate','Tỷ lệ hồ sơ có cảnh báo',ROSE,'dot')]:
        figure.add_trace(go.Scatter(x=candidates['threshold'], y=candidates[column], mode='lines', name=name,
            line={'color':color, 'width':2, 'dash':dash}, hovertemplate='%{x:.2%}<br>%{y:.2%}<extra>%{fullData.name}</extra>'))
    figure.add_vline(x=threshold, line_color=RED, line_dash='dash', line_width=1)
    figure.update_xaxes(title='Ngưỡng · validation', tickformat='.0%', range=[0, 1])
    figure.update_yaxes(tickformat='.0%', range=[0, 1])
    result['threshold'] = charts._html(figure, 'evaluation-threshold')
    result['capacity_rows'], gains = ranking_capacity(predictions)
    result['gains'] = charts._html(gains, 'evaluation-gains')
    return result
