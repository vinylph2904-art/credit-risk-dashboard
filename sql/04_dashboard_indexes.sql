-- Index tra cuu lich su theo ho so. Khong doi gia tri du lieu hoac feature.
-- Chi chay mot lan; kiem tra SHOW INDEX neu CSDL da co cac index nay.
USE home_credit_ml;
CREATE INDEX ix_dashboard_curr ON raw_bureau (SK_ID_CURR);
CREATE INDEX ix_dashboard_curr_month ON raw_credit_card_balance (SK_ID_CURR, MONTHS_BALANCE);
CREATE INDEX ix_dashboard_curr_month ON raw_pos_cash_balance (SK_ID_CURR, MONTHS_BALANCE);
CREATE INDEX ix_dashboard_curr ON raw_installments_payments (SK_ID_CURR);
CREATE INDEX ix_dashboard_bureau_month ON raw_bureau_balance (SK_ID_BUREAU, MONTHS_BALANCE);
