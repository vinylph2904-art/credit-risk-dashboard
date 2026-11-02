const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');

function layoutResult(options, sourceFolder = path.join(root, 'web/static')) {
  const styles = {};
  const classes = new Set(['report-view', 'neo-workspace', ...options.classes]);
  const document = {
    body: {classList: {contains: name => classes.has(name)}},
    createElement: () => ({getContext: () => options.measure ? {
      measureText: text => ({width: text.length * 6.25})
    } : null}),
  };
  const context = vm.createContext({document, window: {addEventListener() {}}, console});
  for (const name of ['chart_interactions.js', 'report_layout.js']) {
    vm.runInContext(fs.readFileSync(path.join(sourceFolder, name), 'utf8'), context);
  }
  const traces = options.pie ? [{type: 'pie', labels: ['A', 'B'], values: [10, 20]}] : [{
    type: options.heatmap ? 'heatmap' : 'bar', orientation: 'h',
    x: options.heatmap ? ['A', 'B', 'C'] : [1000, 2000],
    y: ['Vay tiền mặt', 'Secondary / secondary special'],
    text: ['1.000.000', '2.000'], texttemplate: '%{text}', textposition: 'outside',
  }];
  const legend = options.legend ? {getBoundingClientRect: () => ({height: 24})} : null;
  const box = {
    classList: {contains: name => name === 'report-chart'},
    getBoundingClientRect: () => ({width: options.width, height: options.height}),
    querySelector: () => legend,
    style: {setProperty(key, value) { styles[key] = value; }},
  };
  const chart = {id: options.id, data: traces, parentElement: box};
  const original = {
    font: {family: 'Segoe UI', size: 13}, showlegend: true,
    barmode: options.stack ? 'stack' : 'group',
    xaxis: {title: {text: 'Amount'}, tickformat: '~s'},
    yaxis: {title: {text: 'Group'}, tickvals: ['Vay tiền mặt', 'Secondary / secondary special']},
    yaxis2: {title: 'Second axis', tickvals: [0, 1], ticktext: ['0', '1.000']},
  };
  const result = context.reportChartLayout(chart, original, traces);
  return JSON.parse(JSON.stringify({result, original, styles}));
}

function fakeDom() {
  const handlers = {}, windowHandlers = {};
  let appended = [];
  function node() {
    const classes = new Set();
    return {
      children: [], style: {}, attrs: {}, dataset: {},
      classList: {add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name)},
      append(...items) { this.children.push(...items); },
      setAttribute(key, value) { this.attrs[key] = value; },
      getAttribute(key) { return this.attrs[key] ?? null; },
      removeAttribute(key) { delete this.attrs[key]; },
      remove() { appended = appended.filter(item => item !== this); },
      getBoundingClientRect() { return {left: 100, top: 100, width: 72, height: 72, right: 172}; },
    };
  }
  const document = {addEventListener(key, callback) { handlers[key] = callback; }, createElement: node,
    body: {append(item) { appended.push(item); }}};
  const window = {innerWidth: 800, innerHeight: 600, addEventListener(key, callback) { windowHandlers[key] = callback; }};
  const context = vm.createContext({document, window, console});
  function load(name) { vm.runInContext(fs.readFileSync(path.join(root, 'web/static', name), 'utf8'), context); }
  function chart(kind) {
    const svg = node(), card = node(), wrapper = {dataset: {miniKind: kind}};
    card.setAttribute('title', 'Card scope');
    const points = ['A: 25% · 25 · 5 observations', 'B: 75% · 75 · 15 observations'].map(text => {
      const mark = node();
      mark.dataset.share = text[0] === 'A' ? .25 : .75;
      mark.querySelector = () => ({textContent: text});
      return mark;
    });
    svg.closest = selector => selector === '.kpi' ? card : selector === '[data-mini-kind]' ? wrapper : svg;
    svg.querySelector = () => ({textContent: 'Chart meaning'});
    svg.querySelectorAll = selector => selector === '[data-kpi-point]' ? points : [];
    return {svg, card, points};
  }
  return {handlers, windowHandlers, load, chart, get appended() { return appended; }};
}

module.exports = {root, layoutResult, fakeDom};
