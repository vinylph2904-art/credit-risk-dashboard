"""Formatting filters used by Jinja templates."""
from datetime import timedelta, timezone
import pandas as pd
from web.financial import PAYMENT_LABELS


def number_format(value):
    return '—' if value is None or pd.isna(value) else f'{value:,.0f}'.replace(',', '.')



def percent_format(value):
    return '—' if value is None or pd.isna(value) else f'{value * 100:.2f}%'.replace('.', ',')



def percentage_points_format(value):
    return '—' if value is None or pd.isna(value) else f'{value * 100:+.2f}'.replace('.', ',')



def small_percent_format(value):
    if value is None or pd.isna(value):
        return '—'
    if 0 < abs(value) < .0001:
        return f'{value * 100:.4f}%'.replace('.', ',')
    return percent_format(value)



def amount_format(value):
    if value is None or pd.isna(value):
        return '—'
    return f'{value:,.1f}'.replace(',', '_').replace('.', ',').replace('_', '.')



def compact_amount_format(value):
    if value is None or pd.isna(value):
        return '—'
    for divisor, label in [(1e9, 'tỷ'), (1e6, 'triệu')]:
        if abs(value) >= divisor:
            return f'{value / divisor:.2f}'.replace('.', ',') + ' ' + label
    return number_format(value)



def payment_outcome_format(value):
    return PAYMENT_LABELS.get(value, 'Chưa xác định kết quả')



def times_format(value):
    if value is None or pd.isna(value):
        return '—'
    return f'{value:,.3f}'.replace(',', '_').replace('.', ',').replace('_', '.') + ' lần'



def localtime_format(value):
    if value is None or pd.isna(value):
        return '—'
    return value.replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=7))).strftime('%d/%m/%Y %H:%M:%S')



def register_template_filters(app):
    app.add_template_filter(number_format, 'number')
    app.add_template_filter(percent_format, 'percent')
    app.add_template_filter(percentage_points_format, 'pp')
    app.add_template_filter(small_percent_format, 'small_percent')
    app.add_template_filter(amount_format, 'amount')
    app.add_template_filter(compact_amount_format, 'compact_amount')
    app.add_template_filter(payment_outcome_format, 'payment_outcome')
    app.add_template_filter(times_format, 'times')
    app.add_template_filter(localtime_format, 'localtime')
