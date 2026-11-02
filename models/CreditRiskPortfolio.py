"""Thống kê tín dụng lịch sử cho các hồ sơ đang quản lý; không tạo feature model."""
import numpy as np
import pandas as pd


class CreditRiskPortfolio:
    def __init__(self, connector):
        self.connector = connector

    def readBureau(self, ids):
        fields = ['SK_ID_CURR', 'SK_ID_BUREAU', 'CREDIT_ACTIVE', 'CREDIT_CURRENCY', 'CREDIT_TYPE',
                  'DAYS_CREDIT', 'DAYS_CREDIT_UPDATE', 'CREDIT_DAY_OVERDUE',
                  'AMT_CREDIT_SUM_DEBT', 'AMT_CREDIT_SUM_OVERDUE']
        if not ids:
            return pd.DataFrame(columns=fields)
        placeholders = ','.join(['%s'] * len(ids))
        return self.connector.queryDataset(f'''SELECT {', '.join(fields)}
            FROM raw_bureau WHERE SK_ID_CURR IN ({placeholders})
            ORDER BY SK_ID_BUREAU''', tuple(ids))

    @staticmethod
    def bureauReport(bureau, profiles, currency, credit_status='Active', group_column='NAME_INCOME_TYPE'):
        data = bureau.loc[bureau['SK_ID_CURR'].isin(profiles['source_application_id'])].copy()
        if data['SK_ID_BUREAU'].duplicated().any():
            raise ValueError('Mã khoản bureau bị trùng; dừng tổng tiền để kiểm tra nguồn.')
        raw_n = len(data)
        valid_time = ((data['DAYS_CREDIT'] <= 0) & (data['DAYS_CREDIT_UPDATE'] <= 0)
                      & (data['DAYS_CREDIT_UPDATE'] >= data['DAYS_CREDIT']))
        invalid_time_n = int((~valid_time).sum())
        data = data.loc[valid_time].copy()
        if credit_status != 'all':
            data = data.loc[data['CREDIT_ACTIVE'] == credit_status].copy()
        data = data.loc[data['CREDIT_CURRENCY'] == currency].copy()
        debt = pd.to_numeric(data['AMT_CREDIT_SUM_DEBT'], errors='coerce')
        overdue = pd.to_numeric(data['AMT_CREDIT_SUM_OVERDUE'], errors='coerce')
        dpd = pd.to_numeric(data['CREDIT_DAY_OVERDUE'], errors='coerce')
        has_pair = np.isfinite(debt) & np.isfinite(overdue) & (debt >= 0) & (overdue >= 0)
        needs_check = has_pair & (debt == 0) & (overdue > 0)
        data['money_valid'] = has_pair & ~needs_check
        data['needs_check'] = needs_check
        data['dpd_valid'] = np.isfinite(dpd) & (dpd >= 0)
        data['is_overdue'] = data['dpd_valid'] & (dpd > 0)
        data['debt'] = debt
        data['overdue'] = overdue
        data['dpd'] = dpd.where(data['dpd_valid'])
        money = data.loc[data['money_valid']]
        total_debt = float(money['debt'].sum()) if len(money) else None
        total_overdue = float(money['overdue'].sum()) if len(money) else None
        overdue_share = total_overdue / total_debt if total_debt is not None and total_debt > 0 else None
        dpd_n = int(data['dpd_valid'].sum())
        overdue_n = int(data['is_overdue'].sum())
        loan_share = overdue_n / dpd_n if dpd_n else None
        bucket_names = ['Không quá hạn', '1–30 ngày', '31–60 ngày', '61–90 ngày', 'Trên 90 ngày']
        buckets = pd.cut(dpd.where(data['dpd_valid']), [-1, 0, 30, 60, 90, np.inf], labels=bucket_names)
        data['dpd_bucket'] = buckets.astype(object).fillna('Chưa xác định')
        bucket_rows = []
        for label in bucket_names + ['Chưa xác định']:
            n = int((data['dpd_bucket'] == label).sum())
            bucket_rows.append({'label': label, 'n': n, 'share': n / len(data) if len(data) else 0})

        # Ghép sau khi mỗi khoản đã có đúng một dòng, không ghép transaction thô.
        owners = profiles[['source_application_id', 'profile_id', 'case_label',
                           'NAME_INCOME_TYPE', 'NAME_CONTRACT_TYPE', 'review_status']]
        data = data.merge(owners, left_on='SK_ID_CURR', right_on='source_application_id',
                          how='left', validate='many_to_one')
        data['valid_debt'] = data['debt'].where(data['money_valid'])
        data['valid_overdue'] = data['overdue'].where(data['money_valid'])
        groups = data.groupby(group_column, dropna=False).agg(
            profiles_n=('profile_id', 'nunique'), loans_n=('SK_ID_BUREAU', 'size'),
            money_n=('money_valid', 'sum'), dpd_n=('dpd_valid', 'sum'),
            overdue_n=('is_overdue', 'sum'), debt=('valid_debt', 'sum'),
            overdue=('valid_overdue', 'sum')).reset_index()
        groups.loc[groups['money_n'] == 0, ['debt', 'overdue']] = np.nan
        groups['overdue_share'] = groups['overdue_n'] / groups['dpd_n'].where(groups['dpd_n'] > 0)
        groups = groups.sort_values(['overdue', 'debt'], ascending=False, na_position='last')
        pending = profiles.loc[profiles['review_status'] != 'reviewed']
        pending_counts = pending.groupby(group_column, dropna=False).size()
        groups['pending_n'] = groups[group_column].map(pending_counts).fillna(0).astype(int)
        groups = groups.rename(columns={group_column: 'segment'})
        by_profile = data.groupby('source_application_id').agg(
            bureau_loan_n=('SK_ID_BUREAU', 'size'), bureau_money_n=('money_valid', 'sum'),
            bureau_debt=('valid_debt', 'sum'), bureau_overdue=('valid_overdue', 'sum'),
            bureau_dpd_max=('dpd', 'max'))
        by_profile.loc[by_profile['bureau_money_n'] == 0, ['bureau_debt', 'bureau_overdue']] = np.nan
        return {'data': data, 'groups': groups, 'by_profile': by_profile,
                'buckets': bucket_rows, 'raw_n': raw_n, 'invalid_time_n': invalid_time_n,
                'loans_n': len(data), 'profiles_n': int(data['SK_ID_CURR'].nunique()),
                'money_n': len(money), 'excluded_n': len(data) - len(money),
                'exception_n': int(needs_check.sum()), 'dpd_n': dpd_n, 'overdue_n': overdue_n,
                'debt': total_debt, 'overdue': total_overdue,
                'money_share': overdue_share, 'loan_share': loan_share}

    def readCard(self, ids, months=None):
        columns = ['SK_ID_CURR', 'SK_ID_PREV', 'MONTHS_BALANCE', 'AMT_BALANCE',
                   'AMT_CREDIT_LIMIT_ACTUAL', 'SK_DPD']
        if not ids:
            return pd.DataFrame(columns=columns)
        placeholders = ','.join(['%s'] * len(ids))
        sql = f'''SELECT {', '.join(columns)} FROM raw_credit_card_balance
            WHERE SK_ID_CURR IN ({placeholders}) AND MONTHS_BALANCE < 0'''
        params = list(ids)
        if months is not None:
            sql += ' AND MONTHS_BALANCE >= %s'
            params.append(-months)
        return self.connector.queryDataset(sql + ' ORDER BY SK_ID_PREV, MONTHS_BALANCE', tuple(params))

    @staticmethod
    def cardReport(card):
        data = card.drop_duplicates().copy()
        duplicate_n = len(card) - len(data)
        keys = ['SK_ID_PREV', 'MONTHS_BALANCE']
        ambiguous = data.duplicated(keys, keep=False)
        ambiguous_n = int(ambiguous.sum())
        # Một snapshot mâu thuẫn không được tự chọn một dòng đại diện.
        latest_month = data.groupby('SK_ID_PREV')['MONTHS_BALANCE'].transform('max')
        latest = data.loc[(data['MONTHS_BALANCE'] == latest_month) & ~ambiguous].copy()
        balance = pd.to_numeric(latest['AMT_BALANCE'], errors='coerce')
        limit = pd.to_numeric(latest['AMT_CREDIT_LIMIT_ACTUAL'], errors='coerce')
        valid = np.isfinite(balance) & np.isfinite(limit) & (balance >= 0) & (limit > 0)
        latest['utilization'] = (balance / limit).where(valid)
        valid_rows = latest.loc[valid]
        median = float(valid_rows['utilization'].median()) if len(valid_rows) else None
        bins = [0, .25, .5, .75, 1, np.inf]
        names = ['0–25%', '25–50%', '50–75%', '75–100%', 'Trên 100%']
        categories = pd.cut(valid_rows['utilization'], bins, labels=names, include_lowest=True)
        distribution = []
        for label in names:
            n = int((categories == label).sum())
            distribution.append({'label': label, 'n': n, 'share': n / len(valid_rows) if len(valid_rows) else 0})
        profile_util = valid_rows.groupby('SK_ID_CURR')['utilization'].median()
        return {'data': latest, 'valid_n': len(valid_rows), 'loans_n': int(data['SK_ID_PREV'].nunique()),
                'profiles_n': int(valid_rows['SK_ID_CURR'].nunique()), 'median': median,
                'excluded_n': int(data['SK_ID_PREV'].nunique()) - len(valid_rows),
                'ambiguous_n': ambiguous_n, 'duplicate_n': duplicate_n,
                'distribution': distribution, 'profile_util': profile_util}

    def readPayments(self, ids, months=None):
        fields = ['SK_ID_CURR', 'SK_ID_PREV', 'NUM_INSTALMENT_VERSION', 'NUM_INSTALMENT_NUMBER',
                  'DAYS_INSTALMENT', 'DAYS_ENTRY_PAYMENT', 'AMT_INSTALMENT', 'AMT_PAYMENT']
        if not ids:
            return pd.DataFrame(columns=fields)
        placeholders = ','.join(['%s'] * len(ids))
        sql = f'''SELECT {', '.join(fields)} FROM raw_installments_payments
            WHERE SK_ID_CURR IN ({placeholders}) AND DAYS_INSTALMENT <= 0'''
        # Cửa sổ hiển thị theo ngày tương đối, không thay feature hoặc pipeline.
        params = list(ids)
        if months is not None:
            sql += ' AND DAYS_INSTALMENT >= %s'
            params.append(-30 * months)
        return self.connector.queryDataset(sql + ' ORDER BY SK_ID_PREV, NUM_INSTALMENT_NUMBER, DAYS_ENTRY_PAYMENT', tuple(params))

    @staticmethod
    def paymentReport(payments):
        keys = ['SK_ID_CURR', 'SK_ID_PREV', 'NUM_INSTALMENT_VERSION', 'NUM_INSTALMENT_NUMBER']
        data = payments.copy()
        raw_n = len(data)
        for column in ['AMT_INSTALMENT', 'AMT_PAYMENT', 'DAYS_INSTALMENT', 'DAYS_ENTRY_PAYMENT']:
            data[column] = pd.to_numeric(data[column], errors='coerce')
        valid = (data[keys].notna().all(axis=1) & np.isfinite(data['AMT_INSTALMENT'])
                 & np.isfinite(data['AMT_PAYMENT']) & (data['AMT_INSTALMENT'] > 0)
                 & (data['AMT_PAYMENT'] >= 0) & np.isfinite(data['DAYS_INSTALMENT']) & (data['DAYS_INSTALMENT'] <= 0)
                 & np.isfinite(data['DAYS_ENTRY_PAYMENT']) & (data['DAYS_ENTRY_PAYMENT'] <= 0))
        data = data.loc[valid].copy()
        data['paid_by_due'] = data['AMT_PAYMENT'].where(
            data['DAYS_ENTRY_PAYMENT'] <= data['DAYS_INSTALMENT'], 0)
        periods = data.groupby(keys, sort=False).agg(
            payment_rows=('AMT_PAYMENT', 'size'), paid=('AMT_PAYMENT', 'sum'),
            paid_by_due=('paid_by_due', 'sum'), scheduled=('AMT_INSTALMENT', 'min'),
            scheduled_max=('AMT_INSTALMENT', 'max'), due=('DAYS_INSTALMENT', 'min'),
            due_max=('DAYS_INSTALMENT', 'max')).reset_index()
        consistent = (periods['scheduled'] == periods['scheduled_max']) & (periods['due'] == periods['due_max'])
        version_n = periods.groupby(['SK_ID_CURR', 'SK_ID_PREV', 'NUM_INSTALMENT_NUMBER'])['NUM_INSTALMENT_VERSION'].transform('nunique')
        ambiguous = ~consistent | (version_n > 1)
        excluded_periods = int(ambiguous.sum())
        periods = periods.loc[~ambiguous].copy()
        covered = periods['paid'] >= periods['scheduled']
        on_time = periods['paid_by_due'] >= periods['scheduled']
        periods['status'] = 'Chưa thấy trả đủ'
        periods.loc[covered & ~on_time, 'status'] = 'Trả đủ sau hạn'
        periods.loc[on_time, 'status'] = 'Trả đủ đúng hạn'
        completed_n = int(covered.sum())
        on_time_n = int(on_time.sum())
        rate = on_time_n / completed_n if completed_n else None
        # Ngày đầu tiên tổng các lần trả đạt đủ tiền kỳ, không dùng ngày trả cuối.
        usable = data.merge(periods[keys + ['scheduled', 'due']], on=keys, how='inner', validate='many_to_one', suffixes=('', '_period'))
        usable = usable.sort_values(keys + ['DAYS_ENTRY_PAYMENT'])
        usable['paid_so_far'] = usable.groupby(keys)['AMT_PAYMENT'].cumsum()
        reached = usable.loc[usable['paid_so_far'] >= usable['scheduled']]
        completed = reached.groupby(keys)['DAYS_ENTRY_PAYMENT'].min().rename('completed_at')
        periods = periods.merge(completed, on=keys, how='left', validate='one_to_one')
        periods['delay_days'] = (periods['completed_at'] - periods['due']).clip(lower=0)
        distribution = []
        for label in ['Trả đủ đúng hạn', 'Trả đủ sau hạn', 'Chưa thấy trả đủ']:
            n = int((periods['status'] == label).sum())
            distribution.append({'label': label, 'n': n, 'share': n / len(periods) if len(periods) else 0})
        return {'data': periods, 'raw_n': raw_n, 'valid_rows_n': len(data),
                'excluded_periods_n': excluded_periods, 'periods_n': len(periods),
                'completed_n': completed_n, 'on_time_n': on_time_n, 'rate': rate,
                'uncovered_n': int((~covered).sum()), 'distribution': distribution}

    def readMonthly(self, ids, source, months=12):
        if source == 'bureau':
            columns = ['SK_ID_CURR', 'loan_id', 'MONTHS_BALANCE', 'state']
            if not ids:
                return pd.DataFrame(columns=columns)
            placeholders = ','.join(['%s'] * len(ids))
            sql = f'''SELECT b.SK_ID_CURR, m.SK_ID_BUREAU AS loan_id, m.MONTHS_BALANCE, m.STATUS AS state
                FROM raw_bureau b JOIN raw_bureau_balance m ON m.SK_ID_BUREAU=b.SK_ID_BUREAU
                WHERE b.SK_ID_CURR IN ({placeholders}) AND m.MONTHS_BALANCE < 0
                  AND b.DAYS_CREDIT<=0 AND b.DAYS_CREDIT_UPDATE<=0 AND b.DAYS_CREDIT_UPDATE>=b.DAYS_CREDIT'''
        elif source in ['pos', 'card']:
            columns = ['SK_ID_CURR', 'loan_id', 'MONTHS_BALANCE', 'dpd']
            if not ids:
                return pd.DataFrame(columns=columns)
            placeholders = ','.join(['%s'] * len(ids))
            table = 'raw_pos_cash_balance' if source == 'pos' else 'raw_credit_card_balance'
            sql = f'''SELECT SK_ID_CURR, SK_ID_PREV AS loan_id, MONTHS_BALANCE, SK_DPD AS dpd
                FROM {table} WHERE SK_ID_CURR IN ({placeholders}) AND MONTHS_BALANCE<0'''
        else:
            raise ValueError('Nguồn lịch sử không hợp lệ.')
        params = list(ids)
        if months is not None:
            sql += ' AND MONTHS_BALANCE >= %s'
            params.append(-months)
        return self.connector.queryDataset(sql + ' ORDER BY loan_id, MONTHS_BALANCE', tuple(params))

    @staticmethod
    def monthlyReport(history, source):
        data = history.drop_duplicates().copy()
        duplicate_n = len(history) - len(data)
        ambiguous = data.duplicated(['loan_id', 'MONTHS_BALANCE'], keep=False)
        ambiguous_n = int(ambiguous.sum())
        data = data.loc[~ambiguous].copy()
        if source == 'bureau':
            known = data['state'].isin(['0', '1', '2', '3', '4', '5'])
            data['known'] = known
            data['is_overdue'] = known & (data['state'] != '0')
            closed_n = int((data['state'] == 'C').sum())
            unknown_n = int((~known & (data['state'] != 'C')).sum())
        else:
            data['dpd'] = pd.to_numeric(data['dpd'], errors='coerce')
            known = np.isfinite(data['dpd']) & (data['dpd'] >= 0)
            data['known'] = known
            data['is_overdue'] = known & (data['dpd'] > 0)
            closed_n = 0
            unknown_n = int((~known).sum())
        monthly = data.groupby('MONTHS_BALANCE').agg(
            n=('loan_id', 'size'), known_n=('known', 'sum'), overdue_n=('is_overdue', 'sum')).reset_index()
        monthly['share'] = monthly['overdue_n'] / monthly['known_n'].where(monthly['known_n'] > 0)
        pairs = pd.DataFrame(columns=['SK_ID_CURR', 'loan_id', 'from_state', 'to_state'])
        transitions = []
        states = ['0', '1', '2', '3', '4', '5', 'C']
        if source == 'bureau':
            data = data.sort_values(['loan_id', 'MONTHS_BALANCE'])
            data['from_state'] = data.groupby('loan_id')['state'].shift(1)
            previous_month = data.groupby('loan_id')['MONTHS_BALANCE'].shift(1)
            consecutive = data['MONTHS_BALANCE'] - previous_month == 1
            valid_states = data['state'].isin(states) & data['from_state'].isin(states)
            pairs = data.loc[consecutive & valid_states, ['SK_ID_CURR', 'loan_id', 'from_state', 'state']].copy()
            pairs = pairs.rename(columns={'state': 'to_state'})
            counts = pairs.groupby(['from_state', 'to_state']).size()
            for from_state in states:
                total = int((pairs['from_state'] == from_state).sum())
                cells = []
                for to_state in states:
                    n = int(counts.get((from_state, to_state), 0))
                    cells.append({'to_state': to_state, 'n': n, 'share': n / total if total else None})
                transitions.append({'from_state': from_state, 'n': total, 'cells': cells})
        return {'data': data, 'monthly': monthly, 'pairs': pairs, 'transitions': transitions,
                'states': states, 'pair_n': len(pairs), 'ambiguous_n': ambiguous_n,
                'rows_n': len(data), 'loans_n': int(data['loan_id'].nunique()),
                'profiles_n': int(data['SK_ID_CURR'].nunique()),
                'unknown_n': unknown_n, 'closed_n': closed_n, 'duplicate_n': duplicate_n}
