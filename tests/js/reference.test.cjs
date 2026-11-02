const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const {root} = require('./helpers.cjs');

const context = vm.createContext({document: {addEventListener() {}}, Intl});
vm.runInContext(fs.readFileSync(path.join(root, 'web/static/kpi_reference.js'), 'utf8'), context);

test('reference states retain missing values and equality tolerance', () => {
  assert.equal(context.compareKpiReference(NaN, .1), 'unavailable');
  assert.equal(context.compareKpiReference(.1, Infinity), 'unavailable');
  assert.equal(context.compareKpiReference(.1 + 1e-12, .1), 'equal');
  assert.equal(context.compareKpiReference(.2, .1), 'above');
  assert.equal(context.compareKpiReference(0, .1), 'below');
});

test('reference labels retain Vietnamese number formatting and units', () => {
  assert.equal(context.formatKpiReference(.125, 'percent'), '12,5%');
  assert.equal(context.formatKpiReference(3.267, 'times'), '3,267 lần');
  assert.equal(context.formatKpiReference(1000, 'amount'), '1.000 đơn vị tiền nguồn');
  assert.equal(context.formatKpiReference(NaN, 'amount'), 'Chưa đủ dữ liệu');
});
