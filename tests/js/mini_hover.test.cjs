const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const {root, fakeDom} = require('./helpers.cjs');

function setup() {
  const dom = fakeDom();
  if (fs.existsSync(path.join(root, 'web/static/chart_tooltips.js'))) dom.load('chart_tooltips.js');
  dom.load('kpi_mini_hover.js');
  return dom;
}

test('donut chooses the visible sector, clears the empty center and restores card title', () => {
  const dom = setup(), chart = dom.chart('donut');
  dom.handlers.pointermove({target: chart.svg, clientX: 155, clientY: 117});
  assert.equal(dom.appended[0].children[0].textContent, 'A');
  assert.equal(chart.card.getAttribute('title'), null);
  assert.equal(chart.points[0].classList.contains('is-mini-active'), true);
  dom.handlers.pointermove({target: chart.svg, clientX: 109, clientY: 136});
  assert.equal(dom.appended.length, 1);
  assert.equal(dom.appended[0].children[0].textContent, 'B');
  dom.handlers.pointermove({target: chart.svg, clientX: 136, clientY: 136});
  assert.equal(dom.appended.length, 0);
  assert.equal(chart.card.getAttribute('title'), 'Card scope');
});

test('keyboard and dynamically replaced charts keep the same tooltip lifecycle', () => {
  const dom = setup(), first = dom.chart('donut');
  dom.handlers.focusin({target: first.svg});
  dom.handlers.keydown({target: first.svg, key: 'ArrowRight', preventDefault() {}});
  assert.equal(dom.appended[0].children[0].textContent, 'B');
  dom.handlers.keydown({target: first.svg, key: 'Escape'});
  assert.equal(dom.appended.length, 0);
  const next = dom.chart('horizontal');
  const target = {closest: selector => selector === '.kpi-mini-chart svg' ? next.svg : next.points[1]};
  dom.handlers.pointermove({target, clientX: 150, clientY: 125});
  assert.equal(dom.appended[0].children[0].textContent, 'B');
  dom.handlers.scroll();
  assert.equal(dom.appended.length, 0);
  assert.equal(next.svg.getAttribute('aria-describedby'), null);
});
