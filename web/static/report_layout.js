let reportResizeObserver;
let reportResizeFrame;
const reportTables = new WeakMap();

function openReportFilters() {
  const filters = document.querySelector('.filter-dropdown');
  if (!filters) return;
  if (filters.tagName === 'DIALOG') {
    if (!filters.open) filters.showModal();
  } else filters.open = true;
}

function sizeReportTables() {
  document.querySelectorAll('[data-report-table]').forEach(container => {
    const rows = [...container.querySelectorAll('tbody tr')];
    const viewport = container.querySelector('.table-scroll');
    const pager = container.querySelector('.report-table-pager');
    if (!rows.length || !viewport || !pager) return;
    let state = reportTables.get(container);
    if (!state) {
      state = {page: 0, size: 0};
      reportTables.set(container, state);
      pager.innerHTML = '<span aria-live="polite"></span><button type="button" aria-label="Trang trước">‹</button><button type="button" aria-label="Trang sau">›</button>';
      const buttons = pager.querySelectorAll('button');
      buttons[0].addEventListener('click', () => { state.page--; sizeReportTables(); });
      buttons[1].addEventListener('click', () => { state.page++; sizeReportTables(); });
      rows.forEach(row => row.querySelectorAll('td').forEach(cell => {
        // Full values remain available when narrow columns shorten the text.
        cell.title = cell.textContent.trim();
      }));
    }
    const headerHeight = container.querySelector('thead').getBoundingClientRect().height;
    const visibleRow = rows.find(row => !row.hidden) || rows[0];
    const rowHeight = visibleRow.getBoundingClientRect().height || 28;
    const available = viewport.getBoundingClientRect().height - headerHeight - 2;
    const size = Math.max(1, Math.min(Number(container.dataset.maxRows) || 5, Math.floor(available / rowHeight)));
    const oldStart = state.page * state.size;
    if (size !== state.size) state.page = Math.floor(oldStart / size);
    state.size = size;
    const pages = Math.max(1, Math.ceil(rows.length / size));
    state.page = Math.max(0, Math.min(state.page, pages - 1));
    const start = state.page * size;
    rows.forEach((row, index) => { row.hidden = index < start || index >= start + size; });
    pager.querySelector('span').textContent = `${start + 1}–${Math.min(start + size, rows.length)} / ${rows.length}`;
    const buttons = pager.querySelectorAll('button');
    buttons[0].disabled = state.page === 0;
    buttons[1].disabled = state.page >= pages - 1;
    buttons.forEach(button => { button.hidden = pages === 1; });
  });
}

function applyChartFamilyLayout(chartContext) {
  const {chart, original, layout, compact, legend} = chartContext;
  if (chart.id === 'segment-chart') {
    layout.margin.t = 28;
    layout.legend.y = 1.18;
  }
  if (chart.id === 'payment-chart') layout.margin = {l: 4, r: 4, t: 6, b: 6};
  if (chart.id === 'risk-histogram') layout.margin.t = 26;
  if (document.body.classList.contains('overview-view') || document.body.classList.contains('portfolio-view')) {
    layout.margin.b = compact ? 26 : 32;
    layout.margin.t = chart.id === 'risk-histogram' ? 22 : 8;
    if (chart.id === 'credit-exposure') {
      layout.margin.t = 56;
      layout.legend.y = 1.16;
      layout.legend.yanchor = 'bottom';
    }
    if (chart.id === 'overview-exposure') {
      layout.margin = {l: 6, r: 10, t: 32, b: 25};
      layout.legend.y = 1.22;
    }
    if (chart.id === 'risk-concentration') layout.margin.t = 32;
  }
  if (document.body.classList.contains('financial-view') && chart.id.startsWith('finance-')) {
    layout.margin = {l: compact ? 10 : 14, r: compact ? 16 : 24,
      t: original.showlegend ? (compact ? 34 : 48) : (compact ? 14 : 22), b: compact ? 38 : 52};
    layout.font = {...original.font, size: 12};
    layout.legend = {...original.legend, y: compact ? 1.02 : 1.1, yanchor: 'bottom', font: {size: 12}};
    if (compact && Array.isArray(original.yaxis?.tickvals) && chart.id !== 'finance-overview-history-summary') {
      layout.yaxis = {...original.yaxis, ticktext: original.yaxis.tickvals.map(value => {
        const text = String(value);
        return text.length > 21 ? text.slice(0, 20) + '…' : text;
      })};
    }
    if (chart.id === 'finance-concentration') layout.margin.t = compact ? 20 : 34;
    if (chart.id === 'finance-overview-loan-distribution' || chart.id === 'finance-overview-ratio-distribution') {
      layout.margin.t = 28;
      layout.margin.r = 38;
    }
    if (chart.id === 'finance-segment-history') {
      layout.margin.t = compact ? 48 : 64;
      layout.legend = {...layout.legend, y: compact ? 1.02 : 1.04, font: {size: 12}};
    }
  }
  if (legend) {
    layout.showlegend = false;
    layout.margin.t = 12;
  }
  if (document.body.classList.contains('history-view')) {
    layout.font = {...original.font, size: 12};
    layout.margin = {l: 12, r: 24, t: 16, b: compact ? 36 : 42};
    if (chart.id === 'payment-chart') layout.margin = {l: 10, r: 10, t: 12, b: 12};
  }
}

function applyReportAxesLayout(chartContext) {
  const {chart, original, layout, width, legend} = chartContext;
  if (document.body.classList.contains('report-view')) {
    layout.legend = {...layout.legend, orientation: 'h', x: .5, xanchor: 'center', y: 1.02,
      yanchor: 'bottom', itemsizing: 'constant', font: {family: 'Inter, Segoe UI, Arial, sans-serif', size: 11, color: '#86737e'}};
    if (chart.id.startsWith('finance-overview-')) layout.margin = {l: 12, r: 24, t: 12, b: 48};
    if (chart.data?.length === 1 && chart.data[0].type !== 'pie' && !['stack', 'relative'].includes(original.barmode)) layout.showlegend = false;
    ['xaxis', 'yaxis', 'yaxis2'].forEach(key => {
      const axis = layout[key];
      if (!axis) return;
      layout[key] = {...axis, showgrid: false, zeroline: false, showline: false, ticks: '',
        tickfont: {...axis.tickfont, color: '#86737e'},
        title: {...axis.title, font: {...axis.title?.font, color: '#86737e'}}};
      if (axis.tickformat && !axis.tickvals && axis.type !== 'category') layout[key].nticks = 5;
    });
    if (chart.id === 'finance-overview-credit-composition') {
      layout.showlegend = !legend;
      layout.width = Math.min(width, 360);
      layout.margin = {l: 12, r: 12, t: legend ? 12 : 44, b: 12};
      layout.legend.title = {text: ''};
    }
    if (chart.id === 'finance-overview-asset-ownership') {
      layout.showlegend = !legend;
      layout.margin = {l: 12, r: 24, t: legend ? 12 : 44, b: 36};
      layout.xaxis = {...layout.xaxis, title: {text: ''}};
      layout.legend.title = {text: ''};
    }
  }
}

function applyPortfolioChartLayout(chartContext) {
  const {chart, original, layout, traces} = chartContext;
  if (document.body.classList.contains('financial-view') && document.body.classList.contains('portfolio-view')) {
    layout.font = {...layout.font, size: 13};
    layout.margin = {...layout.margin, l: 10, r: 30, b: 48};
    ['xaxis', 'yaxis'].forEach(key => {
      if (layout[key]) layout[key] = {...layout[key], automargin: true,
        tickfont: {...layout[key].tickfont, size: 12}};
    });
    if (chart.id === 'finance-segment-ratio-heatmap') {
      layout.margin = {...layout.margin, r: 78, b: 62};
      layout.xaxis = {...layout.xaxis, tickmode: 'array',
        tickvals: traces[0]?.x,
        ticktext: ['Đòn bẩy<br>khoản vay', 'Niên kim /<br>thu nhập', 'Tài trợ<br>hàng hóa'],
        tickangle: 0, automargin: true};
    }
    if (chart.id === 'finance-credit-segments') {
      layout.margin = {...layout.margin, l: 8, r: 16, b: 52};
      layout.uniformtext = {minsize: 12, mode: 'hide'};
      layout.xaxis = {...layout.xaxis, nticks: 3, tickformat: '~s'};
    }
    if (chart.id === 'finance-credit-segments' || chart.id === 'finance-segment-history') {
      layout.yaxis = {...layout.yaxis, ticktext: (original.yaxis?.tickvals || []).map(value =>
        String(value).split(/\s+/).reduce((lines, word) => {
          if (lines[lines.length - 1].length + word.length > 14) lines.push(word);
          else lines[lines.length - 1] += (lines[lines.length - 1] ? ' ' : '') + word;
          return lines;
        }, ['']).join('<br>'))};
      layout.xaxis = {...layout.xaxis, nticks: 3};
    }
  }
}

function applyChartGutters(chartContext) {
  const {isPaymentDoughnut, legend, layout, traces} = chartContext;
  if (isPaymentDoughnut && !legend && layout.showlegend !== false) {
    layout.margin.t = Math.max(layout.margin.t, 56);
    layout.legend.y = 1.1;
    layout.legend.yanchor = 'bottom';
  }
  // Outside value labels need the same breathing room on every tab and after resize.
  traces.forEach(trace => {
    if (trace.texttemplate !== '%{text}' || !Array.from(trace.text || []).some(Boolean)) return;
    if ((trace.type === 'bar' && trace.orientation === 'h') || trace.textposition === 'middle right') {
      layout.margin.r = Math.max(layout.margin.r, 64);
    } else if (trace.type === 'bar' || trace.textposition === 'top center') {
      layout.margin.t = Math.max(layout.margin.t, 28);
    }
  });
  if (document.body.classList.contains('neo-workspace')) {
    layout.paper_bgcolor = 'rgba(0,0,0,0)';
    layout.plot_bgcolor = 'rgba(0,0,0,0)';
  }
}

function applyCompactChartAxes(chartContext) {
  const {chart, original, layout, traces, width} = chartContext;
  // Apply compact labels last, after compact/portfolio layout overrides.
  if (document.body.classList.contains('portfolio-view') && document.body.classList.contains('financial-view') && original.yaxis?.tickvals) {
    const wrapLabel = value => String(value).replace(/<br>/g, ' ').replace(/\s*\/\s*/g, ' / ').split(/\s+/).reduce((lines, word) => {
      if (lines.at(-1).length + word.length + 1 > 17) lines.push(word);
      else lines[lines.length - 1] += (lines.at(-1) ? ' ' : '') + word;
      return lines;
    }, ['']).join('<br>');
    layout.yaxis = {...layout.yaxis, tickmode: 'array', tickvals: original.yaxis.tickvals,
      ticktext: original.yaxis.tickvals.map(wrapLabel), automargin: true};
  }
  const compactLabel = value => String(value).replace(/\d{1,3}(?:\.\d{3})+(?:,\d+)?/g,
    number => compactChartNumber(Number(number.replaceAll('.', '').replace(',', '.'))));
  ['xaxis', 'yaxis', 'yaxis2'].forEach(key => {
    const axis = layout[key];
    if (!axis) return;
    if (axis.ticktext) axis.ticktext = axis.ticktext.map(compactLabel);
    else if (axis.tickvals?.some(value => typeof value === 'string')) axis.ticktext = axis.tickvals.map(compactLabel);
    else {
      const coordinate = key === 'xaxis' ? 'x' : 'y';
      const categories = traces.flatMap(trace => Array.from(trace[coordinate] || [])).filter(value => typeof value === 'string');
      if (categories.some(value => /\d{1,3}(?:\.\d{3})+/.test(value))) {
        axis.tickmode = 'array';
        axis.tickvals = [...new Set(categories)];
        axis.ticktext = axis.tickvals.map(compactLabel);
      }
    }
  });
  ['xaxis', 'xaxis2', 'yaxis', 'yaxis2'].forEach(key => {
    if (!layout[key]) return;
    const title = layout[key].title;
    layout[key].title = {...(typeof title === 'string' ? {text: title} : title),
      font: {family: 'Inter, Segoe UI, Arial, sans-serif', size: 12, color: '#766e74', weight: 400}};
  });
  if (document.body.classList.contains('portfolio-view')) {
    const categories = original.yaxis?.tickvals || traces.find(trace => trace.orientation === 'h' || trace.type === 'heatmap')?.y;
    if (categories?.length && Array.from(categories).every(value => typeof value === 'string')) {
      layout.yaxis = {...layout.yaxis, tickmode: 'array', tickvals: Array.from(categories),
        ticktext: Array.from(categories).map(value => String(value).replace(/Secondary\s*\/\s*secondary special/i,
          'Secondary /<br>secondary special').replace(/Incomplete higher/i, 'Incomplete<br>higher')),
        automargin: true};
      // Fit the actual wrapped/compacted labels instead of reserving 132px
      // on every categorical chart, even when its labels are very short.
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      const fontSize = Number(layout.yaxis.tickfont?.size) || 12;
      if (context) context.font = `${fontSize}px Inter, "Segoe UI", Arial, sans-serif`;
      const measure = value => {
        const text = String(value).replace(/<[^>]*>/g, '');
        return context ? context.measureText(text).width : text.length * fontSize * .55;
      };
      const labels = layout.yaxis.ticktext.map(compactLabel);
      layout.yaxis.ticktext = labels;
      const labelWidth = Math.max(0, ...labels.flatMap(label => label.split(/<br\s*\/?\s*>/i)).map(measure));
      const titleSpace = layout.yaxis.title?.text ? 20 : 0;
      layout.margin.l = Math.ceil(Math.min(width * .32, labelWidth + 12 + titleSpace));
      layout.yaxis.automargin = true;
      // Keep room for the real outside value text, not a fixed 64px gutter.
      const outside = traces.filter(trace => trace.textposition === 'outside' || trace.textposition === 'middle right');
      const values = outside.flatMap(trace => Array.from(trace.text || [])).filter(Boolean);
      const valueWidth = Math.max(0, ...values.map(measure));
      layout.margin.r = Math.ceil(Math.min(64, Math.max(16, valueWidth + 12)));
    }
  }
}

function reportChartLayout(chart, original, traces = chart.data || []) {
  const layout = {...original};
  if (!document.body.classList.contains('report-view')) return layout;
  const box = chart.parentElement.classList.contains('report-chart') ? chart.parentElement : chart;
  const width = Math.round(box.getBoundingClientRect().width);
  const legend = box.querySelector('.chart-horizontal-legend');
  const isPaymentDoughnut = chart.id === 'payment-chart';
  const legendGap = isPaymentDoughnut ? 36 : 8;
  const legendOffset = legend ? Math.ceil(legend.getBoundingClientRect().height) + legendGap : 0;
  box.style.setProperty('--chart-legend-offset', `${legendOffset}px`);
  const height = Math.round(box.getBoundingClientRect().height - legendOffset);
  if (width < 1 || height < 1) return layout;
  const compact = height < 270;
  layout.width = width;
  layout.height = height;
  layout.autosize = false;
  layout.font = {...original.font, size: 12};
  layout.margin = {l: 12, r: 28, t: 12, b: compact ? 33 : 39};
  layout.legend = {...original.legend, font: {size: 12}, y: 1.13};
  const chartContext = {chart, original, traces, layout, width, compact, legend, isPaymentDoughnut};
  applyChartFamilyLayout(chartContext);
  applyReportAxesLayout(chartContext);
  applyPortfolioChartLayout(chartContext);
  applyChartGutters(chartContext);
  applyCompactChartAxes(chartContext);
  return layout;
}

function sizeReportCharts() {
  // Size by the actual marks, including charts loaded through dashboard navigation.
  document.body.style.removeProperty('--financial-plot-height');
  document.querySelectorAll('.financial-chart-grid > .report-panel, .history-chart-grid > .report-panel').forEach(panel => {
    const script = panel.querySelector('.chart-data');
    if (!script) return;
    const traces = JSON.parse(script.textContent).figure.data || [];
    let layout = 'standard';
    if (traces.some(trace => trace.type === 'pie')) {
      layout = 'compact';
    } else if (traces.some(trace => trace.type === 'heatmap' ||
        (['scatter', 'scattergl'].includes(trace.type) && (trace.mode || 'lines+markers').includes('lines')))) {
      layout = 'wide';
    } else if (traces.length && traces.every(trace => trace.type === 'bar' && trace.orientation === 'h' && (trace.y?.length || 0) <= 2)) {
      layout = 'short';
    }
    if (panel.dataset.chartLayout !== layout) panel.dataset.chartLayout = layout;
    if (document.body.classList.contains('portfolio-view') && document.body.classList.contains('financial-view')) {
      const labels = [...new Set(traces.flatMap(trace => {
        const horizontal = trace.orientation === 'h' || trace.type === 'heatmap';
        return horizontal ? Array.from(trace.y || []).filter(value => typeof value === 'string') : [];
      }))];
      const longNames = labels.some(label => label.length > 24);
      const dense = labels.length > 5;
      panel.dataset.dense = String(dense || longNames);
      const plotHeight = Math.max(200, labels.length * (longNames ? 32 : 24) + 76);
      const box = panel.querySelector('.report-chart');
      if (box) box.style.setProperty('--portfolio-chart-height', plotHeight + 'px');
    }
  });
  if (document.body.classList.contains('portfolio-view') && document.body.classList.contains('financial-view')) {
    document.querySelectorAll('.financial-chart-grid').forEach(grid => {
      const panels = [...grid.children].filter(panel => panel.matches('.report-panel'));
      panels.forEach(panel => {
        panel.querySelector('.report-chart')?.style.removeProperty('--portfolio-row-height');
        panel.style.removeProperty('--portfolio-heading-height');
      });
      const rows = new Map();
      panels.forEach(panel => {
        const top = Math.round(panel.offsetTop);
        if (!rows.has(top)) rows.set(top, []);
        rows.get(top).push(panel);
      });
      rows.forEach(row => {
        const height = Math.max(...row.map(panel => parseFloat(panel.querySelector('.report-chart')?.style.getPropertyValue('--portfolio-chart-height')) || 200));
        const headingHeight = Math.max(...row.map(panel => panel.querySelector('.panel-heading')?.getBoundingClientRect().height || 52));
        row.forEach(panel => panel.style.setProperty('--portfolio-heading-height', headingHeight + 'px'));
        row.forEach(panel => panel.querySelector('.report-chart')?.style.setProperty('--portfolio-row-height', height + 'px'));
      });
    });
  }
}


function resizeReportCanvas(root = document) {
  sizeReportCharts();
  sizeReportTables();
  if (!window.Plotly) return;
  root.querySelectorAll('.dashboard-chart').forEach(chart => {
    if (!chart.data || !chart.getBoundingClientRect().width || chart.closest('dialog:not([open])')) return;
    const script = document.querySelector(`.chart-data[data-chart="${chart.id}"]`);
    if (script) {
      const figure = JSON.parse(script.textContent).figure;
      Plotly.relayout(chart, reportChartLayout(chart, figure.layout, figure.data));
    }
    if (chart.id === 'finance-concentration' && chart.data?.[0]) {
      const mode = 'markers';
      if (chart.data[0].mode !== mode) Plotly.restyle(chart, {mode}, [0]);
    }
  });
}

function initializeReportCanvas() {
  reportResizeObserver?.disconnect();
  if (!document.body.classList.contains('report-view')) return;
  sizeReportCharts();
  sizeReportTables();
  if (typeof ResizeObserver !== 'undefined') {
    reportResizeObserver = new ResizeObserver(() => {
      cancelAnimationFrame(reportResizeFrame);
      reportResizeFrame = requestAnimationFrame(() => resizeReportCanvas());
    });
    document.querySelectorAll('.report-chart, [data-report-table]').forEach(box => reportResizeObserver.observe(box));
  }
}


