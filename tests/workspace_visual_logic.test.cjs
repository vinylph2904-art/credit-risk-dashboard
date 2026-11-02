const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({Intl, ArrayBuffer, window: {addEventListener() {}}, document: {}});
vm.runInContext(fs.readFileSync('web/static/chart_interactions.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('web/static/report_layout.js', 'utf8'), context);
const normalize = value => JSON.parse(JSON.stringify(value));
function simplify(id, data, layout = {}) {
  const figure = {data, layout};
  context.simplifyDashboardFigure({id}, figure);
  return figure;
}

for (const id of ['finance-overview-loan-distribution', 'finance-segment-rate', 'dpd-chart', 'card-chart', 'score-chart', 'another-tab']) {
  test(`${id}: same maximum rule, underlying data and hover preserved`, () => {
    const trace = {type: 'bar', x: ['A', 'B', 'C'], y: [10, 50, 25], customdata: [1, 2, 3], hovertemplate: '%{y}'};
    const figure = simplify(id, [trace]);
    assert.deepEqual(normalize(trace.text), ['', '50', '']);
    assert.equal(trace.textposition, 'outside');
    assert.equal(trace.cliponaxis, false);
    assert.deepEqual(trace.y, [10, 50, 25]);
    assert.deepEqual(trace.customdata, [1, 2, 3]);
    assert.equal(trace.hovertemplate, '%{y}');
    assert.equal(figure.layout.showlegend, false);
  });
}
test('horizontal percentages retain useful precision rather than rounding to whole percent', () => {
  const trace = {type: 'bar', orientation: 'h', x: [.071, .1234], y: ['A', 'B']};
  simplify('finance-segment-rate', [trace], {xaxis: {tickformat: '.0%'}});
  assert.deepEqual(normalize(trace.text), ['', '12,3%']);
});
test('secondary numeric axis supplies the unit', () => {
  const trace = {type: 'bar', x: ['A', 'B'], y: [.5, .75], yaxis: 'y2'};
  simplify('another-tab', [trace], {yaxis2: {tickformat: '.0%'}});
  assert.deepEqual(normalize(trace.text), ['', '75%']);
});
test('ties are labelled, zero and missing values do not create false highlights', () => {
  const trace = {type: 'bar', x: ['A', 'B', 'C', 'D', 'E'], y: [null, 7, NaN, 0, 7]};
  simplify('another-tab', [trace]);
  assert.deepEqual(normalize(trace.text), ['', '7', '', '', '7']);
  const zero = {type: 'bar', y: [0, 0, null]};
  simplify('another-tab', [zero]);
  assert.deepEqual(normalize(zero.text), ['', '', '']);
});
test('dense series and typed numeric arrays do not silently lose the maximum', () => {
  const trace = {type: 'bar', y: new Float64Array(Array.from({length: 25}, (_, i) => i))};
  simplify('another-tab', [trace]);
  assert.equal(trace.text.filter(Boolean).length, 1);
  assert.equal(trace.text[24], '24');
});
test('ratio decimals and compact monetary notation retain their units', () => {
  const ratio = {type: 'bar', y: [1.25, 3.267]};
  simplify('ratio', [ratio], {yaxis: {tickformat: '.2f'}});
  assert.equal(ratio.text[1], '3,27');
  const money = {type: 'bar', y: [100, 5000000]};
  simplify('money', [money], {yaxis: {tickformat: '~s'}});
  assert.equal(money.text[1], new Intl.NumberFormat('vi-VN', {notation: 'compact', maximumFractionDigits: 1}).format(5000000));
});
test('stacked bars keep direct segment labels and semantic colors', () => {
  const trace = {type: 'bar', y: [.93, .07], text: ['93%', '7%'], textposition: 'inside', marker: {color: '#cf283d'}};
  simplify('stack', [trace], {barmode: 'stack', showlegend: true});
  assert.deepEqual(trace.text, ['93%', '7%']);
  assert.equal(trace.textposition, 'inside');
  assert.equal(trace.marker.color, '#cf283d');
});
test('categorical dot plots highlight the maximum; invisible box-tooltip anchors do not', () => {
  const dot = {type: 'scatter', mode: 'markers', x: [.1, .3], y: ['A', 'B']};
  simplify('risk-segment-chart', [dot], {xaxis: {tickformat: '.0%'}});
  assert.deepEqual(normalize(dot.text), ['', '30%']);
  assert.equal(dot.textposition, 'middle right');
  const helper = {type: 'scatter', mode: 'markers', x: [1, 2], y: ['A', 'A'], meta: {compactTooltip: true}};
  simplify('ratio-box', [helper]);
  assert.equal(helper.text, undefined);
});
test('donuts, heatmaps, boxplots and numeric curves retain their own reading rules', () => {
  const pie = {type: 'pie', values: [93, 7], marker: {colors: ['#dadce0', '#cf283d']}};
  const heatmap = {type: 'heatmap', z: [[1, 2]], texttemplate: '%{z}'};
  const box = {type: 'box', median: [3]};
  const line = {type: 'scatter', mode: 'lines+markers', x: [0, 1], y: [0, 1]};
  simplify('specialized', [pie, heatmap, box, line]);
  assert.equal(pie.texttemplate, '%{percent:.0%}');
  assert.equal(pie.textposition, 'inside');
  assert.deepEqual(pie.marker.colors, ['#dadce0', '#cf283d']);
  assert.equal(heatmap.texttemplate, '%{z}');
  assert.equal(box.text, undefined);
  assert.equal(line.text, undefined);
});
test('reapplying presentation after filtering is idempotent', () => {
  const figure = simplify('finance-segment-rate', [{type: 'bar', y: [1, 3]}]);
  const first = normalize(figure);
  context.simplifyDashboardFigure({id: 'finance-segment-rate'}, figure);
  assert.deepEqual(normalize(figure), first);
  figure.data[0].y = [5, 2];
  context.simplifyDashboardFigure({id: 'finance-segment-rate'}, figure);
  assert.deepEqual(normalize(figure.data[0].text), ['5', '']);
});
test('layout leaves room for maximum labels both initially and after resize', () => {
  context.document.body = {classList: {contains: name => name === 'report-view'}};
  const box = {classList: {contains: () => true}, querySelector: () => null, style: {setProperty() {}}, getBoundingClientRect: () => ({width: 400, height: 200})};
  for (const horizontal of [false, true]) {
    const trace = {type: 'bar', orientation: horizontal ? 'h' : 'v', texttemplate: '%{text}', text: ['', '50']};
    const chart = {id: 'another-tab', parentElement: box, data: [trace]};
    const initial = context.reportChartLayout(chart, {}, [trace]);
    const resized = context.reportChartLayout(chart, {});
    assert.deepEqual(normalize(initial.margin), normalize(resized.margin));
    assert.ok(horizontal ? initial.margin.r >= 64 : initial.margin.t >= 28);
  }
});
