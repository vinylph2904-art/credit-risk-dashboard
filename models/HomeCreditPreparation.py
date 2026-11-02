"""Chuẩn bị đặc trưng từ MySQL; dùng lại kết quả trong cùng phiên làm việc."""
import gc

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from models.HomeCreditData import HomeCreditData


class HomeCreditPreparation(HomeCreditData):
    def __init__(self, connector):
        super().__init__(connector)
        self.split = None
        self.feature_index = None
        self.history_results = {}
        self._installment_results = None
        self.scope_rows = []
        self.day_to_year = {
            'DAYS_BIRTH': 'AGE_YEARS',
            'DAYS_EMPLOYED': 'EMPLOYED_YEARS',
            'DAYS_REGISTRATION': 'REGISTRATION_YEARS',
            'DAYS_ID_PUBLISH': 'ID_DOCUMENT_YEARS',
            'DAYS_LAST_PHONE_CHANGE': 'PHONE_CHANGE_YEARS'
        }
        self.period_keys = [
            'SK_ID_CURR', 'SK_ID_PREV', 'NUM_INSTALMENT_VERSION', 'NUM_INSTALMENT_NUMBER'
        ]
        self.payment_columns = self.period_keys + [
            'DAYS_INSTALMENT', 'DAYS_ENTRY_PAYMENT', 'AMT_INSTALMENT', 'AMT_PAYMENT'
        ]

    def loadInputs(self):
        self.split = self.connector.queryDataset(
            "SELECT SK_ID_CURR, dataset_role AS split, cv_fold FROM application_split "
            "WHERE dataset_role IN ('train', 'validation', 'test') ORDER BY SK_ID_CURR"
        )
        self.split['SK_ID_CURR'] = self.split['SK_ID_CURR'].astype('int64')
        self.split['cv_fold'] = self.split['cv_fold'].astype('int8')
        self.train_ids = pd.Index(self.split.loc[self.split['split'] == 'train', 'SK_ID_CURR'])

        metadata = self.loadColumns()
        columns = metadata.loc[metadata['table'] == 'application_train', 'column'].tolist()
        columns.remove('TARGET')
        application = self.readTable('application_train', columns)
        scoring = self.readTable('application_test', columns)
        application = pd.concat([application, scoring], ignore_index=True)
        application = application.set_index('SK_ID_CURR')
        application = application.sort_index()
        self.all_ids = application.index
        self.original_columns = application.columns.tolist()
        self.raw_categorical = application.select_dtypes(
            include=['object', 'string', 'category']).columns.tolist()

        self.feature_index = pd.DataFrame({'SK_ID_CURR': self.all_ids}).merge(
            self.split, on='SK_ID_CURR', how='left', validate='one_to_one')
        self.feature_index['split'] = self.feature_index['split'].fillna('application_test')
        self.feature_index['cv_fold'] = self.feature_index['cv_fold'].fillna(-1).astype('int8')
        assert self.all_ids.is_unique
        assert set(self.split['SK_ID_CURR']).issubset(self.all_ids)
        self.source_counts = self.processOverview().set_index('table')['rows']
        return application

    def prepareApplication(self, application):
        """Apply fixed cleaning rules to the supplied application frame once."""
        is_employment_sentinel = application['DAYS_EMPLOYED'] == 365243
        has_no_car = application['FLAG_OWN_CAR'] == 'N'
        has_car = application['FLAG_OWN_CAR'] == 'Y'
        has_missing_car_age = application['OWN_CAR_AGE'].isna()
        application['EMPLOYED_SENTINEL'] = is_employment_sentinel.astype('int8')
        application['CAR_AGE_NOT_APPLICABLE'] = has_no_car.astype('int8')
        application['CAR_AGE_MISSING_WITH_CAR'] = (has_car & has_missing_car_age).astype('int8')
        application.loc[is_employment_sentinel, 'DAYS_EMPLOYED'] = float('nan')
        application.loc[has_no_car, 'OWN_CAR_AGE'] = float('nan')

        for source, feature in self.day_to_year.items():
            is_observed_day = application[source] <= 0
            observed_days = application[source].where(is_observed_day)
            application[feature] = -observed_days / 365.25
        application = application.drop(columns=list(self.day_to_year))

        for column in self.raw_categorical:
            if (application[column] == '__MISSING__').any():
                raise ValueError('The reserved missing token already exists in source data.')
            values = application[column].astype(object)
            application[column] = values.fillna('__MISSING__')
        return application

    @staticmethod
    def addApplicationRatios(application):
        income = application['AMT_INCOME_TOTAL'].where((application['AMT_INCOME_TOTAL'] > 0))
        goods = application['AMT_GOODS_PRICE'].where((application['AMT_GOODS_PRICE'] > 0))
        family_size = application['CNT_FAM_MEMBERS'].where((application['CNT_FAM_MEMBERS'] > 0))
        application['RATIO_CREDIT_INCOME_RECORDED'] = application['AMT_CREDIT'] / income
        application['RATIO_ANNUITY_INCOME_RECORDED'] = application['AMT_ANNUITY'] / income
        application['RATIO_CREDIT_GOODS_RECORDED'] = application['AMT_CREDIT'] / goods
        application['INCOME_DIV_FAMILY_SIZE_RECORDED'] = application['AMT_INCOME_TOTAL'] / family_size
        return application


    def _addScope(self, table_name, data):
        self.scope_rows.append({
            'source': table_name,
            'source_rows': int(self.source_counts[table_name]),
            'eligible_rows': len(data),
            'train_eligible_rows': int(data['SK_ID_CURR'].isin(self.train_ids).sum())
        })

    def processBureau(self):
        if 'bureau' in self.history_results:
            return self.history_results['bureau']

        sql = '''
            SELECT b.SK_ID_CURR, b.SK_ID_BUREAU, b.DAYS_CREDIT, b.DAYS_CREDIT_UPDATE,
                   b.CREDIT_ACTIVE, b.CREDIT_CURRENCY, b.CREDIT_DAY_OVERDUE,
                   b.AMT_CREDIT_SUM, b.AMT_CREDIT_SUM_DEBT,
                   b.AMT_CREDIT_SUM_OVERDUE, b.AMT_ANNUITY
            FROM raw_bureau AS b
            JOIN application_split AS s ON s.SK_ID_CURR = b.SK_ID_CURR
            WHERE b.DAYS_CREDIT <= 0 AND b.DAYS_CREDIT_UPDATE <= 0
              AND b.DAYS_CREDIT_UPDATE >= b.DAYS_CREDIT
            ORDER BY b._source_row
        '''
        bureau = self.connector.queryDataset(sql)
        bureau = self._convertTypes(bureau, 'bureau')
        bureau = bureau.loc[bureau['SK_ID_CURR'].isin(self.all_ids)].copy()
        assert bureau['SK_ID_BUREAU'].is_unique
        self.bureau_owners = bureau.set_index('SK_ID_BUREAU')['SK_ID_CURR']
        self._addScope('bureau', bureau)
        other_currency = bureau.loc[bureau['SK_ID_CURR'].isin(self.train_ids) & (bureau['CREDIT_CURRENCY'] != 'currency 1')]
        self.currency_example_id = int(other_currency['SK_ID_CURR'].iloc[0]) if len(other_currency) else None
        bureau['ACTIVE_RECORD'] = (bureau['CREDIT_ACTIVE'] == 'Active').astype('int8')
        bureau['CLOSED_RECORD'] = (bureau['CREDIT_ACTIVE'] == 'Closed').astype('int8')
        bureau['OTHER_CURRENCY'] = (bureau['CREDIT_CURRENCY'] != 'currency 1').astype('int8')
        bureau['CREDIT_DAYS_AGO'] = -bureau['DAYS_CREDIT']
        bureau['UPDATE_DAYS_AGO'] = -bureau['DAYS_CREDIT_UPDATE']
        for column in ['AMT_CREDIT_SUM', 'AMT_CREDIT_SUM_DEBT', 'AMT_CREDIT_SUM_OVERDUE', 'AMT_ANNUITY']:
            bureau[column] = bureau[column].where((bureau['CREDIT_CURRENCY'] == 'currency 1'))

        aggregate = bureau.groupby('SK_ID_CURR', sort=False).agg(
            BUR_LOAN_N=('SK_ID_BUREAU', 'size'),
            BUR_ACTIVE_N=('ACTIVE_RECORD', 'sum'),
            BUR_CLOSED_N=('CLOSED_RECORD', 'sum'),
            BUR_OTHER_CURRENCY_N=('OTHER_CURRENCY', 'sum'),
            BUR_C1_CREDIT_MEAN=('AMT_CREDIT_SUM', 'mean'),
            BUR_C1_CREDIT_MAX=('AMT_CREDIT_SUM', 'max'),
            BUR_C1_DEBT_MEAN=('AMT_CREDIT_SUM_DEBT', 'mean'),
            BUR_C1_DEBT_MAX=('AMT_CREDIT_SUM_DEBT', 'max'),
            BUR_C1_OVERDUE_MEAN=('AMT_CREDIT_SUM_OVERDUE', 'mean'),
            BUR_C1_OVERDUE_MAX=('AMT_CREDIT_SUM_OVERDUE', 'max'),
            BUR_C1_ANNUITY_MEAN=('AMT_ANNUITY', 'mean'),
            BUR_OVERDUE_DAYS_MAX=('CREDIT_DAY_OVERDUE', 'max'),
            BUR_CREDIT_DAYS_AGO_MEAN=('CREDIT_DAYS_AGO', 'mean'),
            BUR_RECENT_UPDATE_DAYS_AGO=('UPDATE_DAYS_AGO', 'min'))
        self.history_results['bureau'] = aggregate
        return aggregate

    def processBureauBalance(self, bureau_owners):
        if 'bureau_balance' in self.history_results:
            return self.history_results['bureau_balance']

        balance_parts = []
        balance_rows = 0
        balance_train_rows = 0
        # Nguồn lớn đọc theo lô; chủ khoản đã được xác định ở processBureau().
        sql = '''
            SELECT SK_ID_BUREAU, MONTHS_BALANCE, STATUS
            FROM raw_bureau_balance
            WHERE MONTHS_BALANCE < 0
            ORDER BY _source_row
        '''
        for frame in self.connector.queryBatches(sql, batch_size=500_000):
            frame = self._convertTypes(frame, 'bureau_balance')
            frame = frame.loc[frame['SK_ID_BUREAU'].isin(bureau_owners.index)].copy()
            balance_rows += len(frame)
            balance_train_rows += int(frame['SK_ID_BUREAU'].map(bureau_owners).isin(self.train_ids).sum())
            frame['KNOWN_DPD'] = frame['STATUS'].isin(['0', '1', '2', '3', '4', '5']).astype('int8')
            frame['DPD_MONTH'] = frame['STATUS'].isin(['1', '2', '3', '4', '5']).astype('int8')
            frame['CLOSED_MONTH'] = (frame['STATUS'] == 'C').astype('int8')
            frame['UNKNOWN_MONTH'] = (frame['STATUS'] == 'X').astype('int8')
            frame['STATUS_CODE'] = pd.to_numeric(frame['STATUS'], errors='coerce')
            partial = frame.groupby('SK_ID_BUREAU', sort=False).agg(
                MONTH_N=('MONTHS_BALANCE', 'size'), KNOWN_DPD_N=('KNOWN_DPD', 'sum'),
                DPD_N=('DPD_MONTH', 'sum'), CLOSED_N=('CLOSED_MONTH', 'sum'), UNKNOWN_N=('UNKNOWN_MONTH', 'sum'),
                MAX_CODE=('STATUS_CODE', 'max'), OLDEST_MONTH=('MONTHS_BALANCE', 'min'),
                RECENT_MONTH=('MONTHS_BALANCE', 'max'))
            balance_parts.append(partial)
        loan_balance = pd.concat(balance_parts).groupby(level=0, sort=False).agg({
            'MONTH_N': 'sum', 'KNOWN_DPD_N': 'sum', 'DPD_N': 'sum', 'CLOSED_N': 'sum',
            'UNKNOWN_N': 'sum', 'MAX_CODE': 'max', 'OLDEST_MONTH': 'min', 'RECENT_MONTH': 'max'})
        loan_balance['SK_ID_CURR'] = loan_balance.index.map(bureau_owners)
        loan_balance = loan_balance.reset_index()
        aggregate = loan_balance.groupby('SK_ID_CURR', sort=False).agg(
            BB_LOAN_N=('SK_ID_BUREAU', 'size'),
            BB_MONTH_N=('MONTH_N', 'sum'),
            BB_KNOWN_DPD_MONTH_N=('KNOWN_DPD_N', 'sum'),
            BB_DPD_MONTH_N=('DPD_N', 'sum'),
            BB_CLOSED_MONTH_N=('CLOSED_N', 'sum'),
            BB_UNKNOWN_MONTH_N=('UNKNOWN_N', 'sum'),
            BB_MAX_STATUS_CODE=('MAX_CODE', 'max'),
            BB_OLDEST_MONTH=('OLDEST_MONTH', 'min'),
            BB_RECENT_MONTH=('RECENT_MONTH', 'max'))
        aggregate['BB_DPD_MONTH_SHARE'] = aggregate['BB_DPD_MONTH_N'] / aggregate['BB_KNOWN_DPD_MONTH_N'].where((aggregate['BB_KNOWN_DPD_MONTH_N'] > 0))
        self.scope_rows.append({'source': 'bureau_balance', 'source_rows': int(self.source_counts['bureau_balance']), 'eligible_rows': balance_rows, 'train_eligible_rows': balance_train_rows})
        self.history_results['bureau_balance'] = aggregate
        return aggregate

    def processPrevious(self):
        if 'previous_application' in self.history_results:
            return self.history_results['previous_application']

        sql = '''
            SELECT p.SK_ID_CURR, p.SK_ID_PREV, p.DAYS_DECISION,
                   p.NAME_CONTRACT_STATUS, p.AMT_APPLICATION,
                   p.AMT_CREDIT, p.AMT_ANNUITY, p.CNT_PAYMENT
            FROM raw_previous_application AS p
            JOIN application_split AS s ON s.SK_ID_CURR = p.SK_ID_CURR
            WHERE p.DAYS_DECISION < 0
            ORDER BY p._source_row
        '''
        previous = self.connector.queryDataset(sql)
        previous = self._convertTypes(previous, 'previous_application')
        previous = previous.loc[previous['SK_ID_CURR'].isin(self.all_ids)].copy()
        self._addScope('previous_application', previous)
        previous['APPROVED_RECORD'] = (previous['NAME_CONTRACT_STATUS'] == 'Approved').astype('int8')
        previous['REFUSED_RECORD'] = (previous['NAME_CONTRACT_STATUS'] == 'Refused').astype('int8')
        previous['DECISION_DAYS_AGO'] = -previous['DAYS_DECISION']
        is_approved = previous['NAME_CONTRACT_STATUS'] == 'Approved'
        for column in ['AMT_CREDIT', 'AMT_ANNUITY', 'CNT_PAYMENT']:
            previous['APPROVED_' + column] = previous[column].where(is_approved)
        aggregate = previous.groupby('SK_ID_CURR', sort=False).agg(
            PREV_APPLICATION_N=('SK_ID_PREV', 'size'),
            PREV_APPROVED_N=('APPROVED_RECORD', 'sum'),
            PREV_REFUSED_N=('REFUSED_RECORD', 'sum'),
            PREV_REFUSED_SHARE=('REFUSED_RECORD', 'mean'),
            PREV_REQUESTED_MEAN=('AMT_APPLICATION', 'mean'),
            PREV_APPROVED_CREDIT_MEAN=('APPROVED_AMT_CREDIT', 'mean'),
            PREV_APPROVED_CREDIT_MAX=('APPROVED_AMT_CREDIT', 'max'),
            PREV_APPROVED_ANNUITY_MEAN=('APPROVED_AMT_ANNUITY', 'mean'),
            PREV_APPROVED_PAYMENT_COUNT_MEAN=('APPROVED_CNT_PAYMENT', 'mean'),
            PREV_RECENT_DECISION_DAYS_AGO=('DECISION_DAYS_AGO', 'min'))
        self.history_results['previous_application'] = aggregate
        return aggregate

    def processPos(self):
        if 'pos_cash_balance' in self.history_results:
            return self.history_results['pos_cash_balance']

        # 1e0 và 0e0 giúp AVG trả số thực; bỏ qua DPD âm hoặc thiếu.
        sql = '''
            SELECT p.SK_ID_CURR,
                   COUNT(DISTINCT p.SK_ID_PREV) AS POS_LOAN_N,
                   COUNT(*) AS POS_MONTH_N,
                   COUNT(CASE WHEN p.SK_DPD >= 0 THEN p.SK_DPD END) AS POS_KNOWN_DPD_MONTH_N,
                   AVG(CASE WHEN p.SK_DPD > 0 THEN 1e0
                            WHEN p.SK_DPD = 0 THEN 0e0 END) AS POS_DPD_MONTH_SHARE,
                   MAX(CASE WHEN p.SK_DPD >= 0 THEN p.SK_DPD END) AS POS_DPD_MAX,
                   MAX(CASE WHEN p.SK_DPD_DEF >= 0 THEN p.SK_DPD_DEF END) AS POS_DPD_DEF_MAX,
                   AVG(p.CNT_INSTALMENT_FUTURE) AS POS_FUTURE_INST_MEAN,
                   MIN(p.MONTHS_BALANCE) AS POS_OLDEST_MONTH,
                   MAX(p.MONTHS_BALANCE) AS POS_RECENT_MONTH
            FROM raw_pos_cash_balance AS p
            JOIN application_split AS s ON s.SK_ID_CURR = p.SK_ID_CURR
            WHERE p.MONTHS_BALANCE < 0
            GROUP BY p.SK_ID_CURR
            ORDER BY MIN(p._source_row)
        '''
        aggregate = self.connector.queryDataset(sql).set_index('SK_ID_CURR')
        aggregate = aggregate.loc[aggregate.index.isin(self.all_ids)].copy()
        self.scope_rows.append({
            'source': 'pos_cash_balance',
            'source_rows': int(self.source_counts['pos_cash_balance']),
            'eligible_rows': int(aggregate['POS_MONTH_N'].sum()),
            'train_eligible_rows': int(aggregate.loc[
                aggregate.index.isin(self.train_ids), 'POS_MONTH_N'].sum())
        })
        self.history_results['pos_cash_balance'] = aggregate
        return aggregate

    def processCard(self):
        if 'credit_card_balance' in self.history_results:
            return self.history_results['credit_card_balance']

        sql = '''
            SELECT c.SK_ID_CURR, c.SK_ID_PREV, c.MONTHS_BALANCE, c.AMT_BALANCE,
                   c.AMT_CREDIT_LIMIT_ACTUAL, c.AMT_PAYMENT_TOTAL_CURRENT,
                   c.AMT_DRAWINGS_CURRENT, c.SK_DPD
            FROM raw_credit_card_balance AS c
            JOIN application_split AS s ON s.SK_ID_CURR = c.SK_ID_CURR
            WHERE c.MONTHS_BALANCE < 0
            ORDER BY c._source_row
        '''
        # Giữ các lô nhỏ thay vì fetchall toàn bộ lịch sử thẻ vào RAM.
        parts = []
        for batch in self.connector.queryBatches(sql):
            parts.append(batch)
        if parts:
            card = pd.concat(parts, ignore_index=True)
        else:
            card = pd.DataFrame(columns=[
                'SK_ID_CURR', 'SK_ID_PREV', 'MONTHS_BALANCE', 'AMT_BALANCE',
                'AMT_CREDIT_LIMIT_ACTUAL', 'AMT_PAYMENT_TOTAL_CURRENT',
                'AMT_DRAWINGS_CURRENT', 'SK_DPD'
            ])
        del parts
        card = self._convertTypes(card, 'credit_card_balance')
        card = card.loc[card['SK_ID_CURR'].isin(self.all_ids)].copy()
        self._addScope('credit_card_balance', card)
        card['SK_DPD'] = card['SK_DPD'].where((card['SK_DPD'] >= 0))
        card['OBS_DPD_FLAG'] = (card['SK_DPD'] > 0).astype(float).where(card['SK_DPD'].notna())
        card['BALANCE_LIMIT_RATIO'] = card['AMT_BALANCE'] / card['AMT_CREDIT_LIMIT_ACTUAL'].where((card['AMT_CREDIT_LIMIT_ACTUAL'] > 0))
        aggregate = card.groupby('SK_ID_CURR', sort=False).agg(
            CC_LOAN_N=('SK_ID_PREV', 'nunique'),
            CC_MONTH_N=('MONTHS_BALANCE', 'size'),
            CC_KNOWN_DPD_MONTH_N=('SK_DPD', 'count'),
            CC_DPD_MONTH_SHARE=('OBS_DPD_FLAG', 'mean'),
            CC_DPD_MAX=('SK_DPD', 'max'),
            CC_BALANCE_MEAN=('AMT_BALANCE', 'mean'),
            CC_BALANCE_MAX=('AMT_BALANCE', 'max'),
            CC_LIMIT_MEAN=('AMT_CREDIT_LIMIT_ACTUAL', 'mean'),
            CC_BALANCE_LIMIT_RATIO_MEAN=('BALANCE_LIMIT_RATIO', 'mean'),
            CC_BALANCE_LIMIT_RATIO_MAX=('BALANCE_LIMIT_RATIO', 'max'),
            CC_PAYMENT_TOTAL_MEAN=('AMT_PAYMENT_TOTAL_CURRENT', 'mean'),
            CC_DRAWINGS_MEAN=('AMT_DRAWINGS_CURRENT', 'mean'),
            CC_RECENT_MONTH=('MONTHS_BALANCE', 'max'))
        self.history_results['credit_card_balance'] = aggregate
        return aggregate



    def processInstallments(self):
        """Return features, quality counts and small examples from one SQL pass."""
        if self._installment_results is not None:
            return self._installment_results

        installment_parts = []
        period_example_parts = []
        payment_example_parts = []
        eligible_payment_rows = 0
        train_eligible_payment_rows = 0
        inconsistent_periods = 0
        eligible_periods = 0

        # Chia theo khoảng ID để mỗi lần chỉ giữ một phần lịch sử trong RAM.
        for lower_id in range(int(self.all_ids.min()), int(self.all_ids.max()) + 1, 50_000):
            sql = '''
                SELECT p.SK_ID_CURR, p.SK_ID_PREV, p.NUM_INSTALMENT_VERSION,
                       p.NUM_INSTALMENT_NUMBER, p.DAYS_INSTALMENT,
                       p.DAYS_ENTRY_PAYMENT, p.AMT_INSTALMENT, p.AMT_PAYMENT
                FROM raw_installments_payments AS p
                WHERE p.SK_ID_CURR >= %s AND p.SK_ID_CURR < %s
                  AND p.DAYS_ENTRY_PAYMENT <= 0 AND p.DAYS_INSTALMENT <= 0
                  AND p.AMT_PAYMENT >= 0 AND p.AMT_INSTALMENT > 0
                ORDER BY p._source_row
            '''
            # Mỗi khoảng vẫn có nhiều dòng; đọc lô nhỏ và lọc ID theo all_ids bên dưới.
            parts = []
            for batch in self.connector.queryBatches(sql, (lower_id, lower_id + 50_000)):
                parts.append(batch)
            if parts:
                payments = pd.concat(parts, ignore_index=True)
            else:
                payments = pd.DataFrame(columns=self.payment_columns)
            del parts
            payments = self._convertTypes(payments, 'installments_payments')
            payments = payments.loc[payments['SK_ID_CURR'].isin(self.all_ids)].dropna(subset=self.period_keys)
            eligible_payment_rows += len(payments)
            train_eligible_payment_rows += int(payments['SK_ID_CURR'].isin(self.train_ids).sum())
            # 1. Payment rows -> consistent, versioned periods.
            periods, inconsistent_n = self._groupInstallmentPeriods(payments)
            inconsistent_periods += inconsistent_n
            eligible_periods += len(periods)

            # 2. Periods -> one feature row per application.
            aggregate = self._aggregateInstallmentPeriods(periods)
            installment_parts.append(aggregate)
            # 3. Keep small examples now, without another SQL read or full copy.
            period_example, payment_example = self._installmentExamples(payments, periods)
            period_example_parts.append(period_example)
            payment_example_parts.append(payment_example)
            print(lower_id, ':', len(payments), 'dòng ->', len(periods), 'nhóm kỳ hợp lệ')
            del payments, periods, aggregate, period_example, payment_example
            gc.collect()
        aggregate = pd.concat(installment_parts)
        assert aggregate.index.is_unique
        self.scope_rows.append({
            'source': 'installments_payments',
            'source_rows': int(self.source_counts['installments_payments']),
            'eligible_rows': eligible_payment_rows,
            'train_eligible_rows': train_eligible_payment_rows
        })
        checks = pd.DataFrame([{
            'eligible_payment_rows': eligible_payment_rows,
            'usable_versioned_periods': eligible_periods,
            'inconsistent_versioned_periods': inconsistent_periods
        }])

        self.history_results['installments_payments'] = aggregate
        results = {
            'features': aggregate,
            'checks': checks,
            'period_examples': pd.concat(period_example_parts, ignore_index=True),
            'payment_examples': pd.concat(payment_example_parts, ignore_index=True)
        }
        self._installment_results = results
        return results

    def _groupInstallmentPeriods(self, payments):
        """Sum split payments once per obligation; discard conflicting periods."""
        payments['AFTER_DUE'] = (payments['DAYS_ENTRY_PAYMENT'] > payments['DAYS_INSTALMENT']).astype('int8')
        payments['OBS_LATE_DAYS'] = (payments['DAYS_ENTRY_PAYMENT'] - payments['DAYS_INSTALMENT']).clip(lower=0)
        periods = payments.groupby(self.period_keys, sort=False).agg(
            PAYMENT_ROW_N=('AMT_PAYMENT', 'size'), OBS_PAID=('AMT_PAYMENT', 'sum'),
            SCHEDULED_MIN=('AMT_INSTALMENT', 'min'), SCHEDULED_MAX=('AMT_INSTALMENT', 'max'),
            DUE_MIN=('DAYS_INSTALMENT', 'min'), DUE_MAX=('DAYS_INSTALMENT', 'max'),
            LAST_OBS_PAYMENT=('DAYS_ENTRY_PAYMENT', 'max'), ANY_AFTER_DUE=('AFTER_DUE', 'max'),
            MAX_OBS_LATE_DAYS=('OBS_LATE_DAYS', 'max')).reset_index()
        same_amount = periods['SCHEDULED_MIN'] == periods['SCHEDULED_MAX']
        same_due_date = periods['DUE_MIN'] == periods['DUE_MAX']
        consistent = same_amount & same_due_date
        inconsistent_n = int((~consistent).sum())
        periods = periods.loc[consistent].copy()
        periods['OBS_PAID_SCHEDULED_RATIO'] = periods['OBS_PAID'] / periods['SCHEDULED_MIN']
        periods['OBS_AMOUNT_COVERED'] = (periods['OBS_PAID'] >= periods['SCHEDULED_MIN']).astype('int8')
        periods['LAST_OBS_PAYMENT_DAYS_AGO'] = -periods['LAST_OBS_PAYMENT']
        return periods, inconsistent_n

    @staticmethod
    def _aggregateInstallmentPeriods(periods):
        """Calculate the existing ten installment features per application."""
        return periods.groupby('SK_ID_CURR', sort=False).agg(
            INS_OBS_PAYMENT_ROW_N=('PAYMENT_ROW_N', 'sum'),
            INS_OBS_VERSIONED_PERIOD_N=('SK_ID_PREV', 'size'), INS_OBS_LOAN_N=('SK_ID_PREV', 'nunique'),
            INS_OBS_PAID_SUM=('OBS_PAID', 'sum'), INS_OBS_SCHEDULED_MEAN=('SCHEDULED_MIN', 'mean'),
            INS_OBS_PAID_SCHEDULED_RATIO_MEAN=('OBS_PAID_SCHEDULED_RATIO', 'mean'),
            INS_OBS_AMOUNT_COVERED_SHARE=('OBS_AMOUNT_COVERED', 'mean'),
            INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE=('ANY_AFTER_DUE', 'mean'),
            INS_MAX_OBS_LATE_DAYS=('MAX_OBS_LATE_DAYS', 'max'),
            INS_RECENT_OBS_PAYMENT_DAYS_AGO=('LAST_OBS_PAYMENT_DAYS_AGO', 'min'))

    def _installmentExamples(self, payments, periods):
        """Select one training example per ID range for the notebook report."""
        belongs_to_train = periods['SK_ID_CURR'].isin(self.train_ids)
        has_split_payments = periods['PAYMENT_ROW_N'] > 1
        period_example = periods.loc[belongs_to_train & has_split_payments].head(1)
        payment_example = payments.merge(
            period_example[self.period_keys], on=self.period_keys,
            how='inner', validate='many_to_one')
        return period_example, payment_example

    def clearHistoryResults(self):
        """Release cached history after all feature partitions have been saved."""
        self.history_results.clear()
        self._installment_results = None


    def readPaymentPeriod(self, example):
        sql = '''
            SELECT SK_ID_CURR, SK_ID_PREV, NUM_INSTALMENT_VERSION,
                   NUM_INSTALMENT_NUMBER, DAYS_INSTALMENT,
                   DAYS_ENTRY_PAYMENT, AMT_INSTALMENT, AMT_PAYMENT
            FROM raw_installments_payments
            WHERE SK_ID_CURR = %s AND SK_ID_PREV = %s
              AND NUM_INSTALMENT_VERSION = %s AND NUM_INSTALMENT_NUMBER = %s
            ORDER BY _source_row
        '''
        values = (int(example['SK_ID_CURR']), int(example['SK_ID_PREV']),
                  float(example['NUM_INSTALMENT_VERSION']), int(example['NUM_INSTALMENT_NUMBER']))
        payments = self.connector.queryDataset(sql, values)
        return self._convertTypes(payments, 'installments_payments')

    def readBureauApplication(self, application_id):
        sql = '''
            SELECT SK_ID_CURR, DAYS_CREDIT, DAYS_CREDIT_UPDATE,
                   CREDIT_CURRENCY, AMT_CREDIT_SUM
            FROM raw_bureau WHERE SK_ID_CURR = %s ORDER BY _source_row
        '''
        bureau = self.connector.queryDataset(sql, (int(application_id),))
        return self._convertTypes(bureau, 'bureau')

    @staticmethod
    def makePreprocessor(schema, scale_numeric):
        numeric_steps = [('imputer', SimpleImputer(strategy='median', add_indicator=True,
                                                  keep_empty_features=True))]
        if scale_numeric:
            numeric_steps.append(('scaler', StandardScaler()))
        return ColumnTransformer([
            ('numeric', Pipeline(numeric_steps), schema['numeric']),
            ('categorical', OneHotEncoder(handle_unknown='ignore', sparse_output=True), schema['categorical'])
        ], sparse_threshold=1.0, n_jobs=1)

    def buildModelingDataset(self, application, count_features, source_flags):
        """Join application-level aggregates and add the fixed availability flags."""
        if not application.index.is_unique:
            raise ValueError('Application IDs must be unique before joining history.')
        data = application
        join_rows = []
        for source, history in self.history_results.items():
            if not history.index.is_unique:
                raise ValueError('History aggregate IDs must be unique: ' + source)
            duplicate_columns = [column for column in history.columns if column in data.columns]
            if duplicate_columns:
                raise ValueError('History feature names overlap application features.')
            before_n = len(data)
            matched_n = int(data.index.isin(history.index).sum())
            data = data.join(history, how='left', validate='one_to_one')
            if len(data) != before_n:
                raise ValueError('Joining history changed the application row count.')
            join_rows.append({'source': source, 'before_n': before_n,
                              'after_n': len(data), 'with_usable_source_n': matched_n})
        for primary_count, flag in source_flags.values():
            data[flag] = data[primary_count].notna().astype('int8')
        data[count_features] = data[count_features].fillna(0)
        return data, pd.DataFrame(join_rows)
