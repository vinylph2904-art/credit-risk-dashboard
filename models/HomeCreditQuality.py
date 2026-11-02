"""Kiểm tra dữ liệu train và giữ kết quả để notebook dùng lại."""
import gc

import numpy as np
import pandas as pd

from models.HomeCreditData import HomeCreditData


class HomeCreditQuality(HomeCreditData):
    def __init__(self, connector):
        super().__init__(connector)
        self.train = None
        self.split = None
        self.duplicate_summary = None
        self.duplicate_examples = {}
        self._history_results = None
        self.history_names = [
            'bureau', 'bureau_balance', 'previous_application',
            'pos_cash_balance', 'credit_card_balance', 'installments_payments'
        ]
        self.money_columns = {
            'bureau': ['AMT_CREDIT_SUM', 'AMT_CREDIT_SUM_DEBT', 'AMT_CREDIT_SUM_OVERDUE'],
            'previous_application': ['AMT_CREDIT', 'AMT_ANNUITY', 'AMT_APPLICATION'],
            'credit_card_balance': ['AMT_BALANCE', 'AMT_PAYMENT_CURRENT', 'AMT_CREDIT_LIMIT_ACTUAL'],
            'installments_payments': ['AMT_INSTALMENT', 'AMT_PAYMENT']
        }
        self.category_columns = {
            'bureau_balance': ['STATUS'],
            'previous_application': ['NAME_CONTRACT_STATUS', 'CODE_REJECT_REASON']
        }
        self.logic_columns = {
            'bureau': ['SK_ID_CURR', 'SK_ID_BUREAU', 'DAYS_CREDIT', 'DAYS_ENDDATE_FACT',
                       'DAYS_CREDIT_UPDATE', 'AMT_CREDIT_SUM', 'AMT_CREDIT_SUM_DEBT',
                       'AMT_CREDIT_SUM_OVERDUE'],
            'previous_application': ['SK_ID_CURR', 'SK_ID_PREV', 'DAYS_DECISION',
                                     'DAYS_FIRST_DUE', 'DAYS_LAST_DUE_1ST_VERSION'],
            'credit_card_balance': ['SK_ID_CURR', 'SK_ID_PREV', 'MONTHS_BALANCE',
                                    'AMT_BALANCE', 'AMT_CREDIT_LIMIT_ACTUAL']
        }
        self.installment_key = ['SK_ID_PREV', 'NUM_INSTALMENT_VERSION', 'NUM_INSTALMENT_NUMBER']

    def loadTrain(self):
        if self.train is not None:
            return self.train
        sql = '''SELECT SK_ID_CURR, dataset_role AS split, cv_fold
                 FROM application_split
                 WHERE dataset_role IN ('train', 'validation', 'test')
                 ORDER BY SK_ID_CURR'''
        self.split = self.connector.queryDataset(sql)
        if not self.split['SK_ID_CURR'].is_unique:
            raise ValueError('ID phân tập không duy nhất.')
        self.train = self._readHistory('application_train', None)
        train_ids = self.split.loc[self.split['split'] == 'train', 'SK_ID_CURR']
        if set(self.train['SK_ID_CURR']) != set(train_ids):
            raise ValueError('Dữ liệu train không khớp ID đã chốt.')
        if not self.train['SK_ID_CURR'].is_unique or not self.train['TARGET'].isin([0, 1]).all():
            raise ValueError('ID hoặc nhãn train không hợp lệ.')
        return self.train

    def _historyFrom(self, table_name):
        if table_name == 'bureau_balance':
            return '''FROM raw_bureau_balance h
                      JOIN raw_bureau b ON h.SK_ID_BUREAU = b.SK_ID_BUREAU
                      JOIN application_split s ON b.SK_ID_CURR = s.SK_ID_CURR
                      WHERE s.dataset_role = 'train' '''
        return f'''FROM `raw_{table_name}` h
                   JOIN application_split s ON h.SK_ID_CURR = s.SK_ID_CURR
                   WHERE s.dataset_role = 'train' '''

    def _readHistory(self, table_name, columns):
        self._selectColumns(table_name, columns)
        if columns is None:
            metadata = self.loadColumns()
            columns = metadata.loc[metadata['table'] == table_name, 'column'].tolist()
        fields = []
        for column in columns:
            fields.append(f'h.`{column}`')
        sql = 'SELECT ' + ', '.join(fields) + ' ' + self._historyFrom(table_name)
        sql += ' ORDER BY h._source_row'
        parts = []
        for batch in self.connector.queryBatches(sql):
            parts.append(batch)
        if parts:
            data = pd.concat(parts, ignore_index=True)
        else:
            data = pd.DataFrame(columns=columns)
        return self._convertTypes(data, table_name)

    def _sourceBatches(self, table_name):
        columns = self._selectColumns(table_name, None)
        sql = f'SELECT {columns} FROM `raw_{table_name}` ORDER BY _source_row'
        for batch in self.connector.queryBatches(sql):
            yield self._convertTypes(batch, table_name)

    def _exactDuplicates(self, table_name, repeated_hashes):
        candidates = []
        for batch in self._sourceBatches(table_name):
            hashes = pd.util.hash_pandas_object(batch, index=False)
            selected = hashes.isin(repeated_hashes)
            if selected.any():
                candidates.append(batch.loc[selected].copy())
        data = pd.concat(candidates, ignore_index=True)
        duplicate_n = int(data.duplicated().sum())
        examples = data.loc[data.duplicated(keep=False)].head(10)
        return duplicate_n, examples

    def processDuplicates(self):
        if self.duplicate_summary is not None:
            return self.duplicate_summary
        results = []
        for table_name in sorted(self.table_names):
            hashes = []
            for batch in self._sourceBatches(table_name):
                hashes.append(pd.util.hash_pandas_object(batch, index=False).to_numpy())
            row_hashes = np.concatenate(hashes)
            row_count = len(row_hashes)
            del hashes, batch
            unique_hashes, counts = np.unique(row_hashes, return_counts=True)
            repeated_hashes = unique_hashes[counts > 1]
            del row_hashes, unique_hashes, counts
            duplicate_n = 0
            if len(repeated_hashes):
                duplicate_n, examples = self._exactDuplicates(table_name, repeated_hashes)
                self.duplicate_examples[table_name] = examples
            results.append({
                'table': table_name, 'rows': row_count,
                'duplicate_excess_rows': duplicate_n
            })
            print(table_name, ': đã kiểm tra trùng toàn bộ', row_count, 'dòng', flush=True)
            gc.collect()
        self.duplicate_summary = pd.DataFrame(results)
        return self.duplicate_summary

    def _historyMissing(self, table_name):
        metadata = self.loadColumns()
        columns = metadata.loc[metadata['table'] == table_name, 'column'].tolist()
        owner_column = 'h.SK_ID_CURR'
        if table_name == 'bureau_balance':
            owner_column = 'b.SK_ID_CURR'
        fields = ['COUNT(*) AS _rows', f'COUNT(DISTINCT {owner_column}) AS _owners']
        for column in columns:
            fields.append(f'COALESCE(SUM(h.`{column}` IS NULL), 0) AS `{column}`')
        sql = 'SELECT ' + ', '.join(fields) + ' ' + self._historyFrom(table_name)
        values = self.connector.queryDataset(sql).iloc[0]
        row_count = int(values['_rows'])
        owner_count = int(values['_owners'])
        missing = values[columns].astype('int64')
        result = missing.rename_axis('column').reset_index(name='missing_n')
        result['table'] = table_name
        result['rows'] = row_count
        result['missing_pct'] = result['missing_n'] / row_count * 100
        coverage = {
            'table': table_name, 'train_history_rows': row_count,
            'train_with_history': owner_count,
            'train_without_history': len(self.train) - owner_count,
            'coverage_pct': owner_count / len(self.train) * 100
        }
        return result, coverage

    def _neededColumns(self, table_name):
        metadata = self.loadColumns()
        available = metadata.loc[metadata['table'] == table_name, 'column'].tolist()
        if table_name == 'installments_payments':
            return available
        if table_name == 'bureau_balance':
            return available
        needed = ['SK_ID_CURR']
        needed += self.money_columns.get(table_name, [])
        needed += self.category_columns.get(table_name, [])
        needed += self.logic_columns.get(table_name, [])
        if table_name == 'pos_cash_balance':
            needed += ['MONTHS_BALANCE', 'SK_DPD']
        for column in available:
            if column.startswith('DAYS_') or column == 'MONTHS_BALANCE':
                needed.append(column)
        # Giữ thứ tự cột gốc, mỗi cột xuất hiện một lần.
        return [column for column in available if column in needed]

    def _timeProfile(self, data, table_name):
        rows = []
        for column in data.columns:
            if not column.startswith('DAYS_') and column != 'MONTHS_BALANCE':
                continue
            values = data[column]
            non_sentinel_values = values.loc[values != 365243]
            rows.append({
                'table': table_name, 'column': column, 'rows': len(data),
                'missing_n': int(values.isna().sum()),
                'sentinel_n': int((values == 365243).sum()),
                'positive_excluding_sentinel_n': int((non_sentinel_values > 0).sum()),
                'zero_n': int((values == 0).sum()),
                'min_excluding_sentinel': non_sentinel_values.min(),
                'max_excluding_sentinel': non_sentinel_values.max()
            })
        return rows

    def _moneyProfile(self, data, table_name):
        columns = self.money_columns[table_name]
        values = data[columns]
        result = pd.DataFrame({
            'min': values.min(), 'max': values.max(),
            'negative_n': (values < 0).sum(), 'zero_n': (values == 0).sum()
        })
        result['table'] = table_name
        return result.rename_axis('column').reset_index()

    def _categoryProfile(self, data, table_name):
        results = []
        for column in self.category_columns[table_name]:
            counts = data[column].value_counts(dropna=False).astype(float)
            result = counts.rename_axis('value').reset_index(name='n')
            result['table'] = table_name
            result['column'] = column
            results.append(result)
        return results

    def _logicProfile(self, data, table_name):
        rules = pd.DataFrame(index=data.index)
        if table_name == 'bureau':
            valid_end = (data['DAYS_ENDDATE_FACT'] <= 0) & (data['DAYS_CREDIT'] <= 0)
            valid_update = (data['DAYS_CREDIT_UPDATE'] <= 0) & (data['DAYS_CREDIT'] <= 0)
            valid_debt = (data['AMT_CREDIT_SUM_DEBT'] >= 0) & (data['AMT_CREDIT_SUM'] >= 0)
            valid_overdue = (data['AMT_CREDIT_SUM_OVERDUE'] >= 0) & (data['AMT_CREDIT_SUM_DEBT'] >= 0)
            rules['Ngày kết thúc trước ngày xin vay'] = (
                (data['DAYS_ENDDATE_FACT'] < data['DAYS_CREDIT']).where(valid_end)
            )
            rules['Ngày cập nhật trước ngày xin vay'] = (
                (data['DAYS_CREDIT_UPDATE'] < data['DAYS_CREDIT']).where(valid_update)
            )
            rules['Dư nợ lớn hơn số tiền tín dụng'] = (
                (data['AMT_CREDIT_SUM_DEBT'] > data['AMT_CREDIT_SUM']).where(valid_debt)
            )
            rules['Tiền quá hạn lớn hơn dư nợ'] = (
                (data['AMT_CREDIT_SUM_OVERDUE'] > data['AMT_CREDIT_SUM_DEBT']).where(valid_overdue)
            )
        elif table_name == 'previous_application':
            dates = data[['DAYS_DECISION', 'DAYS_FIRST_DUE', 'DAYS_LAST_DUE_1ST_VERSION']]
            dates = dates.mask(dates == 365243)
            valid_first = dates[['DAYS_FIRST_DUE', 'DAYS_DECISION']].notna().all(axis=1)
            valid_last = dates[['DAYS_LAST_DUE_1ST_VERSION', 'DAYS_FIRST_DUE']].notna().all(axis=1)
            rules['Ngày đến hạn đầu trước ngày quyết định'] = (
                (dates['DAYS_FIRST_DUE'] < dates['DAYS_DECISION']).where(valid_first)
            )
            rules['Ngày đến hạn cuối dự kiến trước kỳ đầu'] = (
                (dates['DAYS_LAST_DUE_1ST_VERSION'] < dates['DAYS_FIRST_DUE']).where(valid_last)
            )
        else:
            valid = (data['AMT_BALANCE'] >= 0) & (data['AMT_CREDIT_LIMIT_ACTUAL'] >= 0)
            rules['Số dư lớn hơn hạn mức cùng tháng'] = (
                (data['AMT_BALANCE'] > data['AMT_CREDIT_LIMIT_ACTUAL']).where(valid)
            )
        result = pd.DataFrame({
            'eligible_n': rules.count(), 'flagged_n': rules.sum().astype('int64')
        })
        result = result.rename_axis('rule').reset_index()
        result['table'] = table_name
        result['flagged_pct'] = result['flagged_n'] / result['eligible_n'].replace(0, np.nan) * 100
        examples = []
        for rule in rules:
            selected = (rules[rule] == True)
            sample = data.loc[selected, self.logic_columns[table_name]].head(5).copy()
            if not sample.empty:
                sample.insert(0, 'rule', rule)
                sample.insert(0, 'table', table_name)
                examples.append(sample)
        return result, examples

    def _paymentProfiles(self, data):
        """Return payment checks and examples without publishing hidden attributes."""
        keys = self.installment_key
        repeated = data.duplicated(keys, keep=False)
        repeated_rows = data.loc[repeated]
        repeated_period_keys = repeated_rows[keys].drop_duplicates()
        sample_keys = repeated_period_keys.head(5)
        installment_key_summary = pd.DataFrame([{
            'train_payment_rows': len(data),
            'duplicate_key_excess_rows': int(data.duplicated(keys).sum()),
            'rows_in_repeated_groups': int(repeated.sum()),
            'repeated_key_groups': len(repeated_period_keys)
        }])
        payment_counts = {
            'train_payment_rows': len(data),
            'missing_payment_date_n': int(data['DAYS_ENTRY_PAYMENT'].isna().sum()),
            'payment_after_due_n': int((data['DAYS_ENTRY_PAYMENT'] > data['DAYS_INSTALMENT']).sum()),
            'payment_below_instalment_n': int((data['AMT_PAYMENT'] < data['AMT_INSTALMENT']).sum())
        }
        payment_sample = repeated_rows.merge(sample_keys, on=keys, how='inner', sort=False)
        payment_sample = payment_sample[data.columns]
        period_sample = payment_sample.groupby(keys).agg(
            payment_rows=('AMT_PAYMENT', 'size'),
            obligation_values=('AMT_INSTALMENT', 'nunique'),
            due_date_values=('DAYS_INSTALMENT', 'nunique'),
            obligation_first=('AMT_INSTALMENT', 'first'),
            payment_total=('AMT_PAYMENT', 'sum'),
            last_payment_day=('DAYS_ENTRY_PAYMENT', 'max')
        ).reset_index()
        sample_groups = payment_sample.groupby(keys)
        payment_totals = sample_groups['AMT_PAYMENT'].sum(min_count=1)
        sample_counts = sample_groups[['AMT_PAYMENT', 'DAYS_ENTRY_PAYMENT']].count()
        sample_sizes = sample_groups.size()
        # Keep the original output order, including all-missing payment totals.
        period_sample['payment_total'] = payment_totals.to_numpy()
        period_sample['missing_payment_amount_n'] = (sample_sizes - sample_counts['AMT_PAYMENT']).to_numpy()
        period_sample['missing_payment_date_n'] = (sample_sizes - sample_counts['DAYS_ENTRY_PAYMENT']).to_numpy()
        period_sample = period_sample[keys + [
            'payment_rows', 'obligation_values', 'due_date_values', 'obligation_first',
            'payment_total', 'missing_payment_amount_n', 'missing_payment_date_n', 'last_payment_day']]
        consistency = repeated_rows.groupby(keys).agg(
            payment_rows=('AMT_INSTALMENT', 'size'),
            obligation_observed_n=('AMT_INSTALMENT', 'count'),
            obligation_distinct_n=('AMT_INSTALMENT', 'nunique'),
            due_date_observed_n=('DAYS_INSTALMENT', 'count'),
            due_date_distinct_n=('DAYS_INSTALMENT', 'nunique')
        )
        rules = pd.DataFrame({
            'Cùng kỳ có nhiều số tiền nghĩa vụ': (consistency['obligation_distinct_n'] > 1).where(
                (consistency['obligation_observed_n'] >= 2)),
            'Cùng kỳ có nhiều ngày đến hạn': (consistency['due_date_distinct_n'] > 1).where(
                (consistency['due_date_observed_n'] >= 2))
        })
        period_logic = pd.DataFrame({
            'eligible_period_n': rules.count(),
            'flagged_period_n': rules.sum().astype('int64')
        })
        period_logic['not_checked_period_n'] = len(consistency) - period_logic['eligible_period_n']
        period_count = len(consistency)
        inconsistent_periods = consistency.loc[(rules == True).any(axis=1)]

        return {
            'repeated_period_keys': repeated_period_keys,
            'sample_keys': sample_keys,
            'installment_key_summary': installment_key_summary,
            'payment_counts': payment_counts,
            'payment_sample': payment_sample,
            'period_sample': period_sample,
            'period_logic': period_logic,
            'period_count': period_count,
            'inconsistent_periods': inconsistent_periods,
        }

    def _historyEDA(self, data, table_name):
        if table_name == 'bureau':
            usable = (data['DAYS_CREDIT'] <= 0) & (data['DAYS_CREDIT_UPDATE'] <= 0)
            usable &= (data['DAYS_CREDIT_UPDATE'] >= data['DAYS_CREDIT'])
            usable &= (data['AMT_CREDIT_SUM_OVERDUE'] >= 0)
            signal = usable & (data['AMT_CREDIT_SUM_OVERDUE'] > 0)
            signal_name = 'overdue_rows'
        else:
            usable = (data['MONTHS_BALANCE'] < 0) & (data['SK_DPD'] >= 0)
            signal = usable & (data['SK_DPD'] > 0)
            signal_name = 'positive_dpd_rows'
        view = data[['SK_ID_CURR']].copy()
        view['usable'] = usable
        view['signal'] = signal
        grouped = view.groupby('SK_ID_CURR').agg(
            source_rows=('SK_ID_CURR', 'size'),
            usable_rows=('usable', 'sum'),
            signal_rows=('signal', 'sum')
        )
        grouped = grouped.rename(columns={'signal_rows': signal_name})
        scope = {
            'source': table_name, 'train_rows': len(data),
            'usable_rows': int(usable.sum()), 'unverified_rows': int((~usable).sum()),
            'train_applications_with_history': len(grouped)
        }
        return grouped, scope

    def processHistory(self):
        """Read each history source once; return all report tables and samples.

        Repeated calls reuse the same dictionary and DataFrames. Notebook cells
        should derive their own views instead of editing these shared results.
        """
        if self._history_results is not None:
            return self._history_results
        self.loadTrain()
        missing_parts = []
        coverage_rows = []
        money_parts = []
        time_rows = self._timeProfile(self.train, 'application_train')
        category_parts = []
        logic_parts = []
        logic_examples = []
        eda_scope = []
        eda_results = {}
        for table_name in self.history_names:
            missing, coverage = self._historyMissing(table_name)
            missing_parts.append(missing)
            coverage_rows.append(coverage)
            columns = self._neededColumns(table_name)
            data = self._readHistory(table_name, columns)
            if len(data) != coverage['train_history_rows']:
                raise ValueError('Số dòng lịch sử không khớp phạm vi train.')
            time_rows.extend(self._timeProfile(data, table_name))
            if table_name in self.money_columns:
                money_parts.append(self._moneyProfile(data, table_name))
            if table_name in self.category_columns:
                category_parts.extend(self._categoryProfile(data, table_name))
            if table_name in self.logic_columns:
                logic, examples = self._logicProfile(data, table_name)
                logic_parts.append(logic)
                logic_examples.extend(examples)
            if table_name == 'installments_payments':
                payment_results = self._paymentProfiles(data)
            if table_name == 'bureau':
                eda_results['bureau'], scope = self._historyEDA(data, table_name)
                eda_scope.append(scope)
            if table_name == 'pos_cash_balance':
                eda_results['pos_cash_balance'], scope = self._historyEDA(data, table_name)
                eda_scope.append(scope)
            print(table_name, ': đã kiểm tra lịch sử train', len(data), 'dòng', flush=True)
            del data
            gc.collect()
        results = {
            'missing': pd.concat(missing_parts, ignore_index=True),
            'coverage': pd.DataFrame(coverage_rows),
            'money': pd.concat(money_parts, ignore_index=True),
            'time_checks': pd.DataFrame(time_rows),
            'categories': pd.concat(category_parts, ignore_index=True),
            'logic': pd.concat(logic_parts, ignore_index=True),
            'logic_examples': logic_examples,
            'eda_scope': pd.DataFrame(eda_scope),
            'bureau_by_app': eda_results['bureau'],
            'pos_by_app': eda_results['pos_cash_balance']
        }
        results.update(payment_results)
        # Publish only after every source succeeds; a failed run can be retried.
        self._history_results = results
        return results
