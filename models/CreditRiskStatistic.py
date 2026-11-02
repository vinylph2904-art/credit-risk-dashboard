"""Thống kê hàng đợi demo, theo vai trò PurchaseStatistic trong bài 56."""
import numpy as np
import pandas as pd

REVIEW_FIELDS = ['AMT_INCOME_TOTAL', 'AMT_ANNUITY',
                 'EXT_SOURCE_1', 'EXT_SOURCE_2', 'EXT_SOURCE_3']


class CreditRiskStatistic:
    @staticmethod
    def applyCohortFilters(data, filters):
        product = filters['product']
        income = filters['income']
        availability = filters['availability']
        if product:
            matches_product = data['NAME_CONTRACT_TYPE'] == product
            data = data.loc[matches_product]
        if income:
            matches_income = data['NAME_INCOME_TYPE'] == income
            data = data.loc[matches_income]
        if availability == 'monitored':
            has_missing_fields = data[REVIEW_FIELDS].isna().any(axis=1)
            data = data.loc[has_missing_fields]
        elif availability == 'no_bureau':
            has_no_bureau = data['HAS_USABLE_BUREAU'] == 0
            data = data.loc[has_no_bureau]

        if filters['amount_min'] is not None:
            data = data.loc[data['AMT_CREDIT'] >= filters['amount_min']]
        if filters['amount_max'] is not None:
            data = data.loc[data['AMT_CREDIT'] <= filters['amount_max']]
        if filters['age_min'] is not None:
            data = data.loc[data['AGE_YEARS'] >= filters['age_min']]
        if filters['age_max'] is not None:
            data = data.loc[data['AGE_YEARS'] <= filters['age_max']]
        return data.copy()

    @staticmethod
    def filterApplications(data, q, status, alert, unassigned, data_check, statuses, data_checks):
        """Lọc bảng hồ sơ bằng các điều kiện đã nhận từ giao diện."""
        if q:
            matches_id = data['source_application_id'].astype(str).str.contains(q, regex=False)
            matches_label = data['case_label'].str.contains(q, case=False, regex=False)
            data = data.loc[matches_id | matches_label]
        if status:
            if status not in [*statuses, 'pending']:
                raise ValueError('Trạng thái không hợp lệ.')
            if status == 'pending':
                matches_status = data['review_status'] != 'reviewed'
            else:
                matches_status = data['review_status'] == status
            data = data.loc[matches_status]
        if alert:
            if alert not in ['1', '0', 'unscored']:
                raise ValueError('Bộ lọc cảnh báo không hợp lệ.')
            if alert == 'unscored':
                matches_alert = data['score'].isna()
            else:
                matches_alert = data['alert'] == int(alert)
            data = data.loc[matches_alert]
        if unassigned:
            is_unassigned = data['assignee'].str.strip() == ''
            data = data.loc[is_unassigned]
        if data_check:
            if data_check not in data_checks:
                raise ValueError('Điều kiện kiểm tra dữ liệu không hợp lệ.')
            if data_check == 'monitored':
                has_missing_fields = data[REVIEW_FIELDS].isna().any(axis=1)
                data = data.loc[has_missing_fields]
            elif data_check == 'no_bureau':
                data = data.loc[(data['HAS_USABLE_BUREAU'] == 0)]
            elif data_check == 'bureau_signal':
                has_bureau = data['HAS_USABLE_BUREAU'] == 1
                has_overdue_days = data['BUR_OVERDUE_DAYS_MAX'] > 0
                has_overdue_amount = data['BUR_C1_OVERDUE_MAX'] > 0
                data = data.loc[has_bureau & (has_overdue_days | has_overdue_amount)]
            elif data_check == 'installment_signal':
                has_installments = data['HAS_USABLE_INSTALLMENTS'] == 1
                has_late_payment = data['INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE'] > 0
                data = data.loc[has_installments & has_late_payment]
            else:
                data = data.loc[data[data_check].isna()]
        return data.copy()

    def __init__(self, profiles, threshold):
        self.profiles = profiles
        self.scored = profiles.loc[profiles['score'].notna()].copy()
        self.threshold = threshold

    def summary(self):
        total = len(self.profiles)
        scored_n = len(self.scored)
        alert_n = int(self.scored['alert'].sum())
        is_pending = self.profiles['review_status'] != 'reviewed'
        pending_n = int(is_pending.sum())
        mean_score = None
        alert_share = None
        if scored_n > 0:
            mean_score = float(self.scored['score'].mean())
            alert_share = alert_n / scored_n
        return {'total': total, 'scored_n': scored_n, 'alert_n': alert_n,
                'unscored_n': total - scored_n, 'pending_n': pending_n,
                'mean_score': mean_score, 'alert_share': alert_share}

    def groupRisk(self, column, min_n=5, baseline_alert_share=None):
        if self.scored.empty:
            return []
        data = self.scored.copy()
        is_alert = data['alert'] == 1
        is_pending = data['review_status'] != 'reviewed'
        is_unassigned = data['assignee'].str.strip() == ''
        data['pending_alert'] = is_alert & is_pending
        data['unassigned_pending'] = data['pending_alert'] & is_unassigned
        groups = data.groupby(column, dropna=False).agg(
            n=('profile_id', 'size'), mean_score=('score', 'mean'),
            alert_n=('alert', 'sum'), alert_share=('alert', 'mean'),
            pending_alert_n=('pending_alert', 'sum'),
            unassigned_pending_n=('unassigned_pending', 'sum'))
        groups = groups.reset_index()
        reference = baseline_alert_share
        if reference is None:
            reference = self.scored['alert'].mean()
        groups['delta_alert_share'] = groups['alert_share'] - reference
        groups['profile_share'] = groups['n'] / len(self.scored)
        alert_n = self.scored['alert'].sum()
        groups['share_of_alerts'] = 0.0
        if alert_n > 0:
            groups['share_of_alerts'] = groups['alert_n'] / alert_n
        groups = groups.loc[(groups['n'] >= min_n)]
        groups = groups.sort_values(['mean_score', 'n', column], ascending=[False, False, True])
        groups[column] = groups[column].fillna('Chưa có thông tin')
        return groups.to_dict('records')

    def alertWorkflow(self):
        is_alert = self.scored['alert'] == 1
        alerts = self.scored.loc[is_alert]
        is_reviewed = alerts['review_status'] == 'reviewed'
        is_pending = ~is_reviewed
        is_unassigned = alerts['assignee'].str.strip() == ''
        alert_n = len(alerts)
        reviewed_n = int(is_reviewed.sum())
        reviewed_share = None
        if alert_n > 0:
            reviewed_share = reviewed_n / alert_n
        return {'alert_n': alert_n, 'reviewed_n': reviewed_n,
                'pending_n': alert_n - reviewed_n,
                'unassigned_n': int(is_unassigned.sum()),
                'unassigned_pending_n': int((is_pending & is_unassigned).sum()),
                'reviewed_share': reviewed_share}

    def creditAmounts(self):
        amounts = pd.to_numeric(self.scored['AMT_CREDIT'], errors='coerce')
        has_amount = amounts.notna()
        is_nonnegative = amounts >= 0
        is_finite = np.isfinite(amounts)
        valid = has_amount & is_nonnegative & is_finite
        eligible = self.scored.loc[valid]
        is_alert = eligible['alert'] == 1
        total_amount = float(eligible['AMT_CREDIT'].sum())
        alert_amount = float(eligible.loc[is_alert, 'AMT_CREDIT'].sum())
        alert_share = None
        if total_amount > 0:
            alert_share = alert_amount / total_amount
        return {'total_amount': total_amount, 'alert_amount': alert_amount,
                'eligible_n': len(eligible), 'excluded_n': int((~valid).sum()),
                'alert_eligible_n': int(is_alert.sum()), 'alert_share': alert_share}

    def dataReadiness(self):
        missing = self.profiles[REVIEW_FIELDS].isna()
        has_missing_fields = missing.any(axis=1)
        has_no_bureau = self.profiles['HAS_USABLE_BUREAU'] == 0
        total = len(self.profiles)
        missing_n = int(has_missing_fields.sum())
        no_bureau_n = int(has_no_bureau.sum())
        missing_share = None
        no_bureau_share = None
        if total > 0:
            missing_share = missing_n / total
            no_bureau_share = no_bureau_n / total
        fields = []
        for name in REVIEW_FIELDS:
            fields.append({'name': name, 'n': int(missing[name].sum())})
        return {'total': total, 'missing_n': missing_n,
                'missing_share': missing_share, 'no_bureau_n': no_bureau_n,
                'no_bureau_share': no_bureau_share, 'fields': fields}

    def diagnostic(self):
        data = self.scored
        all_rows = pd.Series(True, index=data.index)
        has_missing_fields = data[REVIEW_FIELDS].isna().any(axis=1)
        has_no_bureau = data['HAS_USABLE_BUREAU'] == 0
        has_overdue_days = data['BUR_OVERDUE_DAYS_MAX'] > 0
        has_overdue_amount = data['BUR_C1_OVERDUE_MAX'] > 0
        has_bureau_signal = has_overdue_days | has_overdue_amount
        has_bureau_values = (data['BUR_OVERDUE_DAYS_MAX'].notna()
                            | data['BUR_C1_OVERDUE_MAX'].notna())
        bureau_eligible = (data['HAS_USABLE_BUREAU'] == 1) & has_bureau_values
        late_share = data['INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE']
        has_late_payment = late_share > 0
        installment_eligible = (data['HAS_USABLE_INSTALLMENTS'] == 1) & late_share.notna()

        checks = [
            {'key': 'monitored', 'label': 'Thiếu ít nhất một trong 5 trường theo dõi',
             'condition': has_missing_fields, 'eligible': all_rows},
            {'key': 'no_bureau', 'label': 'Không có bureau đủ điều kiện',
             'condition': has_no_bureau, 'eligible': all_rows},
            {'key': 'bureau_signal', 'label': 'Có ghi nhận quá hạn lịch sử bureau',
             'condition': has_bureau_signal, 'eligible': bureau_eligible},
            {'key': 'installment_signal', 'label': 'Có thanh toán sau hạn trong lịch sử kỳ trả nợ',
             'condition': has_late_payment, 'eligible': installment_eligible}
        ]
        rows = []
        for check in checks:
            row = {'key': check['key'], 'label': check['label']}
            for name, alert_value in [('alert', 1), ('normal', 0)]:
                in_group = (data['alert'] == alert_value) & check['eligible']
                n = int((in_group & check['condition']).sum())
                denominator = int(in_group.sum())
                share = None
                if denominator > 0:
                    share = n / denominator
                row[name] = {'n': n, 'denominator': denominator, 'share': share}
            rows.append(row)
        return rows

    def distribution(self):
        edges = sorted(set([0, 0.05, 0.10, self.threshold, 0.25, 0.50, 1.0]))
        scores = self.scored['score'].astype(float)
        counts, _ = np.histogram(scores, bins=edges)
        total = len(scores)
        rows = []
        for low, high, count in zip(edges[:-1], edges[1:], counts):
            share = 0
            if total > 0:
                share = int(count) / total
            rows.append({'label': f'{low:.1%} – {high:.1%}', 'n': int(count),
                         'share': share, 'above_threshold': low >= self.threshold})
        return rows

    @staticmethod
    def recommendations(features, result):
        """Gợi ý xác minh, không suy ra nguyên nhân mô hình hoặc quyết định cho vay."""
        suggestions = []
        if result and result['alert']:
            suggestions.append({'title': 'Ưu tiên thẩm định bổ sung',
                'reason': 'Điểm dự báo đạt ngưỡng cảnh báo của phiên bản đang dùng.',
                'action': 'Đối chiếu thông tin hồ sơ, nghĩa vụ tín dụng và nguồn tiền trả nợ trước khi kết luận.'})
        income = features.get('AMT_INCOME_TOTAL')
        if pd.isna(income) or income <= 0:
            income_reason = 'Thu nhập ghi nhận đang thiếu hoặc bằng 0.'
        else:
            income_reason = 'Thu nhập trong dữ liệu là số tiền ghi nhận, chưa xác minh dòng tiền khả dụng.'
        suggestions.append({'title': 'Xác minh thu nhập và khả năng trả nợ',
            'reason': income_reason,
            'action': 'Đối chiếu chứng từ thu nhập, tính ổn định nguồn thu và các nghĩa vụ phải trả.'})
        bureau_late = features.get('BUR_OVERDUE_DAYS_MAX')
        bureau_amount = features.get('BUR_C1_OVERDUE_MAX')
        if (pd.notna(bureau_late) and bureau_late > 0) or (pd.notna(bureau_amount) and bureau_amount > 0):
            suggestions.append({'title': 'Rà soát lịch sử tín dụng',
                'reason': 'Dữ liệu bureau có ghi nhận quá hạn trong phạm vi lịch sử được sử dụng.',
                'action': 'Xác minh tình trạng cập nhật của khoản vay và làm rõ nguyên nhân; chưa suy ra nợ quá hạn hiện tại.'})
        late_share = features.get('INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE')
        if pd.notna(late_share) and late_share > 0:
            suggestions.append({'title': 'Làm rõ diễn biến thanh toán trước đây',
                'reason': 'Dữ liệu ghi nhận một số nhóm kỳ có khoản thanh toán sau ngày đến hạn.',
                'action': 'Trao đổi về nguồn tiền và nguyên nhân thanh toán sau hạn; đối chiếu hồ sơ kỳ trả nợ gốc.'})
        missing = [key for key in REVIEW_FIELDS if pd.isna(features.get(key))]
        if missing:
            suggestions.append({'title': 'Kiểm tra thông tin còn thiếu',
                'reason': f'{len(missing)} trong 5 trường thu nhập, niên kim và điểm nguồn ngoài đang thiếu.',
                'action': 'Bổ sung thông tin nếu có thể xác minh; thiếu dữ liệu tự nó không chứng minh rủi ro hoặc gian lận.'})
        return suggestions
