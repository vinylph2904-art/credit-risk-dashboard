async function openChartDetails(kind, value, page = 1) {
  if (filtersHaveDraft()) return;
  if (detailRequest) detailRequest.abort();
  const controller = new AbortController();
  detailRequest = controller;
  const url = new URL('/api/dashboard/details', window.location.origin);
  url.search = window.location.search;
  url.searchParams.set('kind', kind);
  url.searchParams.set('value', value);
  url.searchParams.set('detail_page', page);
  detailUrl = url;
  const dialog = document.getElementById('chart-details');
  const content = document.getElementById('chart-detail-content');
  setLoadingState(content, true, 'Đang chuẩn bị dữ liệu chi tiết…', 'Đang tải chi tiết nhóm đã chọn…');
  if (!dialog.open) dialog.showModal();
  try {
    const response = await fetch(url, {signal: controller.signal});
    if (response.status === 401) {
      window.location.assign('/login?next=' + encodeURIComponent(window.location.pathname + window.location.search));
      return;
    }
    if (!response.ok) throw new Error('Không tải được dữ liệu chi tiết. Đóng và thử lại.');
    const html = await response.text();
    if (!controller.signal.aborted) {
      content.innerHTML = html;
      dialog.scrollTop = 0;
    }
  } catch (error) {
    if (detailRequest === controller && error.name !== 'AbortError') content.textContent = error.message;
  } finally {
    if (detailRequest === controller) setLoadingState(content, false);
  }
}

function attachBarFocus(chart) {
  if (!chart.data.some(trace => ['bar', 'pie', 'scatter'].includes(trace.type))) return;
  const markSelector = '.barlayer .point, .pielayer .slice, .scatterlayer .points .point';
  let resetTimer;
  let focusFrame;
  let current;
  const clear = () => {
    clearTimeout(resetTimer);
    cancelAnimationFrame(focusFrame);
    current = null;
    chart.querySelectorAll('.bar-focus-muted, .bar-focus-active').forEach(point => {
      point.classList.remove('bar-focus-muted', 'bar-focus-active');
    });
  };
  chart.on('plotly_hover', event => {
    clearTimeout(resetTimer);
    const point = event.points?.find(item => ['bar', 'pie', 'scatter'].includes(item.data?.type));
    if (!point) { clear(); return; }
    const kind = point.data.type;
    const layer = {bar: '.barlayer', pie: '.pielayer', scatter: '.scatterlayer'}[kind];
    const pointSelector = {bar: '.point', pie: '.slice', scatter: '.points .point'}[kind];
    const bars = chart.data.map((trace, index) => ({trace, index}))
      .filter(item => item.trace.type === kind && item.trace.visible !== 'legendonly' && item.trace.visible !== false);
    const traceIndex = bars.findIndex(item => item.index === point.curveNumber);
    const traces = chart.querySelectorAll(layer + ' .trace');
    const trace = [...traces].find(mark => mark.classList.contains('trace' + chart._fullData?.[point.curveNumber]?.uid)) || traces[traceIndex];
    const active = [...(trace?.querySelectorAll(pointSelector) || [])].find((mark, index) =>
      (mark.__data__?.[0]?.i ?? mark.__data__?.i ?? index) === point.pointNumber);
    if (!active || active === current) return;
    current = active;
    cancelAnimationFrame(focusFrame);
    focusFrame = requestAnimationFrame(() => {
      chart.querySelectorAll(markSelector).forEach(mark => {
        mark.classList.toggle('bar-focus-active', mark === current);
        mark.classList.toggle('bar-focus-muted', mark !== current);
      });
    });
  });
  chart.on('plotly_unhover', () => { resetTimer = setTimeout(clear, 100); });
  chart.on('plotly_afterplot', clear);
  chart.addEventListener('pointerleave', clear);
}

function installHorizontalLegend(chart, figure) {
  chart.parentElement.querySelector('.chart-horizontal-legend')?.remove();
  chart.parentElement.classList.remove('has-horizontal-legend');
  if (figure.layout.showlegend === false) return;
  const traces = figure.data.filter(trace => trace.showlegend !== false);
  if (figure.layout.showlegend !== true && traces.length < 2) return;
  const legend = document.createElement('div');
  legend.className = 'chart-horizontal-legend';
  legend.setAttribute('aria-label', 'Chú giải biểu đồ');
  const colors = figure.layout.colorway || ['#2f7be5', '#a8d6cc', '#2db9d2', '#c9dcf6', '#dde3e8'];
  figure.data.forEach((trace, index) => {
    if (trace.showlegend === false) return;
    const labels = trace.type === 'pie' ? trace.labels : [trace.name || `Chuỗi ${index + 1}`];
    labels.forEach((label, pointIndex) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('aria-pressed', 'true');
      button.title = label;
      const swatch = document.createElement('i');
      const color = trace.type === 'pie' ? trace.marker?.colors?.[pointIndex] : trace.marker?.color || trace.line?.color;
      swatch.style.backgroundColor = typeof color === 'string' ? color : colors[index % colors.length];
      button.append(swatch, document.createTextNode(label));
      button.addEventListener('click', () => {
        const visible = button.getAttribute('aria-pressed') !== 'true';
        button.setAttribute('aria-pressed', String(visible));
        if (trace.type === 'pie') {
          const hidden = new Set(chart.layout.hiddenlabels || []);
          visible ? hidden.delete(label) : hidden.add(label);
          Plotly.relayout(chart, {hiddenlabels: [...hidden]});
        } else Plotly.restyle(chart, {visible: visible ? true : 'legendonly'}, [index]);
      });
      legend.append(button);
    });
  });
  if (!legend.childElementCount) return;
  chart.parentElement.classList.add('has-horizontal-legend');
  chart.before(legend);
}

function attachCompactTooltip(chart) {
  if (!chart.data.some(trace => trace.meta?.compactTooltip)) return;
  let tooltip;
  const hide = () => { tooltip?.remove(); tooltip = null; };
  const position = event => {
    if (!tooltip || !Number.isFinite(event?.clientX)) return;
    const gap = 12;
    const rect = tooltip.getBoundingClientRect();
    const left = event.clientX + gap + rect.width <= window.innerWidth - gap
      ? event.clientX + gap : event.clientX - gap - rect.width;
    const top = event.clientY + gap + rect.height <= window.innerHeight - gap
      ? event.clientY + gap : event.clientY - gap - rect.height;
    tooltip.style.left = `${Math.max(gap, Math.min(left, window.innerWidth - rect.width - gap))}px`;
    tooltip.style.top = `${Math.max(gap, Math.min(top, window.innerHeight - rect.height - gap))}px`;
  };
  chart.on('plotly_hover', event => {
    hide();
    const point = event.points?.find(point => point.data.meta?.compactTooltip);
    if (!point?.customdata) return;
    const [title, rows] = point.customdata;
    tooltip = createCompactChartTooltip(title, rows);
    document.body.append(tooltip);
    position(event.event);
  });
  chart.on('plotly_unhover', hide);
  chart.addEventListener('pointermove', position);
  chart.addEventListener('pointerleave', hide);
  chart.on('plotly_afterplot', hide);
}

window.addEventListener('scroll', () => document.querySelectorAll('.compact-chart-tooltip').forEach(node => node.remove()), true);
window.addEventListener('resize', () => document.querySelectorAll('.compact-chart-tooltip').forEach(node => node.remove()));

function compactChartNumber(value) {
  const absolute = Math.abs(value);
  const unit = absolute >= 1e9 ? [1e9, 'B'] : absolute >= 1e6 ? [1e6, 'M'] : absolute >= 1e3 ? [1e3, 'K'] : [1, ''];
  return new Intl.NumberFormat('vi-VN', {maximumFractionDigits: unit[0] === 1 ? 2 : 1}).format(value / unit[0]) + unit[1];
}

function alignCategoryAxisLabels(chart, traces) {
  if (!chart.id.startsWith('finance-') ||
      !traces.some(trace => (trace.orientation === 'h' || trace.type === 'heatmap') &&
        Array.from(trace.y || []).some(value => typeof value === 'string'))) return;
  const positions = new WeakMap();
  const align = () => {
    const labels = [...chart.querySelectorAll('.yaxislayer-above .ytick text')];
    if (!labels.length) return;
    const originals = labels.map(node => {
      const x = Number(node.getAttribute('x'));
      const previous = positions.get(node);
      return previous && Math.abs(x - previous.applied) < .01 ? previous.original : x;
    });
    const longest = Math.max(...labels.map(node => node.getBBox().width));
    const left = Math.min(...originals) - longest;
    labels.forEach((node, i) => {
      node.setAttribute('text-anchor', 'start');
      node.setAttribute('x', String(left));
      node.querySelectorAll('tspan').forEach(line => {
        line.setAttribute('text-anchor', 'start');
        if (line.hasAttribute('x')) line.setAttribute('x', String(left));
      });
      positions.set(node, {original: originals[i], applied: left});
    });
  };
  chart.on('plotly_afterplot', align);
  align();
}

function compactChartLabels(chart, figure) {
  const compactText = text => String(text).replace(/\d{1,3}(?:\.\d{3})+(?:,\d+)?/g,
    value => compactChartNumber(Number(value.replaceAll('.', '').replace(',', '.'))));
  ['xaxis', 'yaxis', 'yaxis2'].forEach(key => {
    const axis = figure.layout[key];
    if (!axis) return;
    if (axis.ticktext) axis.ticktext = axis.ticktext.map(compactText);
    else if (axis.tickvals?.some(value => typeof value === 'string')) axis.ticktext = axis.tickvals.map(compactText);
    if (!axis.tickvals && !/%|f/.test(axis.tickformat || '')) axis.tickformat = '~s';
  });
  const normalizeTicks = () => chart.querySelectorAll('.xtick text,.ytick text,.y2tick text').forEach(node => {
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const text = walker.currentNode;
      text.nodeValue = text.nodeValue.replace(/(\d)k\b/g, '$1K').replace(/(\d)G\b/g, '$1B');
    }
  });
  chart.on('plotly_afterplot', normalizeTicks);
  normalizeTicks();
}

function highlightChartMaximum(trace, figure, horizontal = trace.orientation === 'h') {
  const values = horizontal ? trace.x : trace.y;
  if (!Array.isArray(values) && !ArrayBuffer.isView(values)) return;
  const numbers = Array.from(values);
  const finite = numbers.filter(value => typeof value === 'number' && Number.isFinite(value));
  const maximum = Math.max(0, ...finite);
  const axisRef = (horizontal ? trace.xaxis : trace.yaxis) || (horizontal ? 'x' : 'y');
  const axis = figure.layout[axisRef[0] + 'axis' + axisRef.slice(1)];
  const tickformat = axis?.tickformat || '';
  const percent = tickformat.includes('%');
  const precision = tickformat.match(/\.(\d+)[f%]/);
  const format = new Intl.NumberFormat('vi-VN', percent
    ? {style: 'percent', maximumFractionDigits: 1}
    : {maximumFractionDigits: precision ? Math.min(2, Number(precision[1])) : 0,
      ...(tickformat.includes('~s') ? {notation: 'compact', maximumFractionDigits: 1} : {})});
  trace.text = numbers.map(value => value === maximum && maximum > 0 ? (percent ? format.format(value) : compactChartNumber(value)) : '');
  trace.texttemplate = '%{text}';
  trace.textposition = trace.type === 'bar' ? 'outside' : 'top center';
  trace.textfont = {...trace.textfont, size: 12, color: '#263849'};
  trace.cliponaxis = false;
}

function simplifyDashboardFigure(chart, figure) {
  const traces = figure.data || [];
  if (chart.id === 'finance-credit-segments') {
    traces.forEach(trace => {
      if (trace.type !== 'bar') return;
      const values = Array.from(trace.x || []);
      trace.text = values.map((value, index) => {
        const total = traces.reduce((sum, item) => sum + (Number(item.x?.[index]) || 0), 0);
        return value > 0 && (!total || value / total >= .18) ? compactChartNumber(value) : '';
      });
      trace.texttemplate = '%{text}';
      trace.textposition = 'inside';
      trace.insidetextanchor = 'middle';
      trace.textfont = {family: 'Inter, Segoe UI, Arial, sans-serif', size: 12,
        color: /^(Có khó khăn|Ghi nhận)/i.test(trace.name || '') ? '#ffffff' : '#263849'};
      trace.constraintext = 'inside';
    });
  }
  traces.forEach(trace => {
    if (trace.type === 'bar') {
      // Values and source denominators remain in the hover data.
      if (!['stack', 'relative'].includes(figure.layout.barmode)) {
        highlightChartMaximum(trace, figure);
      }
    } else if (['scatter', 'scattergl'].includes(trace.type)) {
      // Categorical dot plots follow the same maximum-label rule as bars.
      // Numeric scatterplots, curves and invisible tooltip anchors retain their own semantics.
      const mode = trace.mode || 'lines';
      const categories = values => Array.isArray(values) && values.some(value => typeof value === 'string');
      const horizontal = categories(trace.y);
      const vertical = categories(trace.x);
      if (mode.includes('markers') && !mode.includes('lines') && !trace.meta?.compactTooltip && (horizontal || vertical)) {
        highlightChartMaximum(trace, figure, horizontal);
        trace.mode = 'markers+text';
        trace.textposition = horizontal ? 'middle right' : 'top center';
      } else if (mode.includes('text')) {
        trace.mode = mode.split('+').filter(part => part !== 'text').join('+') || 'markers';
      }
    } else if (trace.type === 'pie') {
      if (!trace.texttemplate) {
        trace.textinfo = 'percent';
        trace.texttemplate = '%{percent:.0%}';
        trace.textposition = 'inside';
      }
    }
  });
  if (traces.length === 1 && traces[0].type !== 'pie' && !['stack', 'relative'].includes(figure.layout.barmode)) figure.layout.showlegend = false;
}

function animateChartMarks(chart) {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  chart.querySelectorAll('.barlayer .trace').forEach((group, index) => {
    const trace = chart._fullData?.find(item => group.classList.contains('trace' + item.uid));
    const horizontal = trace?.orientation === 'h';
    group.querySelectorAll('.point path').forEach((path, pointIndex) => {
      path.style.transformBox = 'fill-box';
      path.style.transformOrigin = horizontal ? 'left center' : 'center bottom';
      path.animate([{transform: horizontal ? 'scaleX(0)' : 'scaleY(0)'}, {transform: 'scale(1)'}],
        {duration: 760, delay: Math.min(index * 35 + pointIndex * 24, 180), easing: 'cubic-bezier(.16,1,.3,1)', fill: 'backwards'});
    });
  });
  chart.querySelectorAll('.pielayer .trace').forEach((group, index) => {
    const box = group.getBBox();
    if (!box.width || !box.height) return;
    const svgNS = 'http://www.w3.org/2000/svg';
    const clip = document.createElementNS(svgNS, 'clipPath');
    const polygon = document.createElementNS(svgNS, 'polygon');
    clip.id = 'pie-reveal-' + chart.id + '-' + index;
    clip.setAttribute('clipPathUnits', 'userSpaceOnUse');
    clip.append(polygon);
    group.ownerSVGElement.append(clip);
    group.setAttribute('clip-path', 'url(#' + clip.id + ')');
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
    const radius = Math.hypot(box.width, box.height);
    const draw = progress => {
      const points = [[cx, cy], [cx, cy - radius]];
      for (let step = 1; step <= 100; step++) {
        const angle = -Math.PI / 2 + Math.PI * 2 * progress * step / 100;
        points.push([cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)]);
      }
      polygon.setAttribute('points', points.map(point => point.join(',')).join(' '));
    };
    draw(0);
    const start = performance.now();
    const frame = now => {
      if (!chart.isConnected) { clip.remove(); return; }
      const progress = Math.min(1, (now - start) / 950);
      draw(1 - Math.pow(1 - progress, 3));
      if (progress < 1) requestAnimationFrame(frame);
      else { group.removeAttribute('clip-path'); clip.remove(); }
    };
    requestAnimationFrame(frame);
  });
}

function applyFinancialChartColors(chart, figure) {
  // Normalize cached/server-generated figures across every dashboard tab.
  const replacements = {'#cf283d':'#2f7be5', '#e5484d':'#2f7be5', '#c8192e':'#2f7be5',
    '#e52f48':'#2f7be5', '#c91f3b':'#245fa8', '#ee627c':'#56afe4', '#f58fa7':'#2db9d2',
    '#fac3d1':'#b9dff4', '#ffb8b8':'#b9dff4', '#d7c8ce':'#fff0d9', '#eedde3':'#dce8f1'};
  const normalize = value => {
    if (typeof value === 'string') return replacements[value.toLowerCase()] || value;
    if (Array.isArray(value)) return value.map(normalize);
    if (value && typeof value === 'object') Object.keys(value).forEach(key => { value[key] = normalize(value[key]); });
    return value;
  };
  normalize(figure);
  if (chart.id.startsWith('evaluation-')) {
    figure.data.forEach(trace => {
      if (trace.type === 'heatmap') trace.colorscale = [[0,'#f0f7fc'],[.4,'#2db9d2'],[.75,'#2f7be5'],[1,'#245fa8']];
      if (trace.line?.color === '#f2a93b') trace.line.color = '#2f7be5';
    });
  }
  if (!chart.id.startsWith('finance-') && !document.body.classList.contains('history-view')) return;
  const blue = '#2f7be5', cyan = '#2db9d2', pale = '#b9dff4', unknown = '#fff0d9', red = '#245fa8';
  const stateColor = name => {
    if (/chưa thấy trả đủ|chưa trả đủ/i.test(name || '')) return '#f2a93b';
    if (/đúng hạn|không quá hạn|dưới ngưỡng/i.test(name || '')) return pale;
    if (/sau hạn|tiền quá hạn|cảnh báo|trên 90/i.test(name || '')) return red;
    if (/chưa xác định|chưa có thông tin/i.test(name || '')) return unknown;
    if (/^(Không ghi nhận|Chưa ghi nhận|Không$)/i.test(name || '')) return pale;
    if (/^(Có khó khăn|Ghi nhận|Có$)/i.test(name || '')) return red;
    return null;
  };
  figure.layout.colorway = [blue, '#a8d6cc', cyan, '#c9dcf6', '#dde3e8'];
  const stacked = ['stack', 'relative'].includes(figure.layout.barmode);
  const blueShades = values => {
    const numbers = Array.from(values || []);
    const valid = numbers.filter(value => typeof value === 'number' && Number.isFinite(value));
    const low = Math.min(...valid), high = Math.max(...valid);
    return numbers.map(value => {
      if (typeof value !== 'number' || !Number.isFinite(value)) return unknown;
      const weight = high > low ? (value - low) / (high - low) : .6;
      const start = [185, 223, 244], end = [47, 123, 229];
      return '#' + start.map((channel, i) => Math.round(channel + (end[i] - channel) * weight).toString(16).padStart(2, '0')).join('');
    });
  };
  figure.data.forEach((trace, index) => {
    if (trace.type === 'scatter' && !trace.meta?.compactTooltip) {
      if ((trace.mode || 'lines').includes('lines')) trace.line = {...trace.line, color: figure.layout.colorway[index % figure.layout.colorway.length]};
    }
    if (trace.type === 'pie') {
      trace.marker = {...trace.marker, colors: trace.labels.map((label, i) =>
        stateColor(label) || figure.layout.colorway[i % figure.layout.colorway.length])};
    } else if (trace.type === 'bar') {
      let color = blueShades(trace.orientation === 'h' ? trace.x : trace.y);
      if (chart.id === 'dpd-chart') color = Array.from(trace.y || []).map(label =>
        /chưa xác định/i.test(label) ? unknown : /trên 90/i.test(label) ? red
        : /61/.test(label) ? '#2f7be5' : /31/.test(label) ? '#56afe4' : '#2db9d2');
      if (chart.id === 'history-chart') color = '#b9dff4';
      if (figure.layout.barmode === 'group') color = stateColor(trace.name) || figure.layout.colorway[index % figure.layout.colorway.length];
      if (stacked) color = stateColor(trace.name) || figure.layout.colorway[index % figure.layout.colorway.length];
      else if (chart.id === 'finance-overview-history-summary') {
        const values = Array.from(trace.orientation === 'h' ? trace.x : trace.y);
        const max = Math.max(...values.filter(Number.isFinite));
        const shades = blueShades(values);
        color = values.map((value, i) => value === max && max > 0 ? '#245fa8' : shades[i]);
      }
      trace.marker = {...trace.marker, color, line: {width: 0}};
    } else if (trace.type === 'box') {
      trace.marker = {...trace.marker, color: figure.layout.colorway[index % figure.layout.colorway.length]};
      trace.fillcolor = '#e0eef8';
    }
  });
}

async function renderDashboardCharts() {
  if (!window.Plotly) {
    const charts = document.querySelectorAll('.dashboard-chart');
    charts.forEach(chart => { chart.classList.add('chart-error'); });
    if (charts.length) throw new Error('Không tải được thư viện biểu đồ.');
    return;
  }
  const config = {responsive: true, displayModeBar: false, scrollZoom: false,
    doubleClick: false, displaylogo: false};
  const rendering = [];
  document.querySelectorAll('.chart-data').forEach(script => {
    const payload = JSON.parse(script.textContent);
    const chart = document.getElementById(script.dataset.chart);
    // Set both states so a reused chart cannot retain a stale click affordance.
    chart.dataset.interactive = String(Boolean(payload.interaction));
    if (chart.id === 'finance-segment-ratio-heatmap') payload.figure.data.forEach(trace => {
      if (trace.type === 'heatmap') trace.colorbar = {...trace.colorbar,
        title: {text: '% chênh', side: 'top', font: {size: 11}},
        thickness: 10, tickfont: {size: 11}, nticks: 3, xpad: 12};
    });
    ['xaxis', 'yaxis', 'yaxis2'].forEach(key => {
      const axis = payload.figure.layout[key];
      if (!axis) return;
      const compact = text => String(text).replace(/\d{1,3}(?:\.\d{3})+/g, value => compactChartNumber(Number(value.replaceAll('.', ''))));
      if (axis.ticktext) axis.ticktext = axis.ticktext.map(compact);
      if (!axis.ticktext && axis.tickvals?.some(value => typeof value === 'string')) axis.ticktext = axis.tickvals.map(compact);
      if (!axis.tickvals && !/%|f/.test(axis.tickformat || '')) axis.tickformat = '~s';
    });
    applyFinancialChartColors(chart, payload.figure);
    simplifyDashboardFigure(chart, payload.figure);
    installHorizontalLegend(chart, payload.figure);
    const layout = document.body?.classList.contains('report-view') ? reportChartLayout(chart, payload.figure.layout, payload.figure.data) : payload.figure.layout;
    if (chart.previousElementSibling?.classList.contains('chart-horizontal-legend')) layout.showlegend = false;
    if (chart.id === 'finance-concentration' && layout.height < 270) {
      payload.figure.data.forEach(trace => { if (trace.type === 'scatter') trace.mode = 'markers'; });
    }
    rendering.push(Plotly.newPlot(chart, payload.figure.data, layout, config).then(() => {
      attachBarFocus(chart);
      attachCompactTooltip(chart);
      chart.classList.add('chart-ready');
      compactChartLabels(chart, payload.figure);
      alignCategoryAxisLabels(chart, payload.figure.data);
      animateChartMarks(chart);
      const action = payload.interaction;
      if (!action) return;
      chart.on('plotly_click', event => {
        if (filtersHaveDraft()) return;
        const point = event.points[0];
        if (action.type === 'filter') {
          const url = action.urls[point[action.key]];
          if (url) updateDashboard(url);
        } else if (action.type === 'drill') {
          let value = action.kind === 'transition' ? point.y + ':' + point.x : point[action.key];
          if (action.index !== undefined && Array.isArray(value)) value = value[action.index];
          if (value !== undefined) openChartDetails(action.kind, String(value));
        } else if (action.type === 'profile') {
          const target = point.customdata?.[0];
          if (typeof target === 'string' && target.startsWith('/') && !target.startsWith('//')) {
            window.location.assign(target);
          }
        }
      });
    }).catch(error => {
      chart.classList.add('chart-error');
      chart.textContent = 'Không tải được biểu đồ.';
      throw error;
    }));
  });
  await Promise.all(rendering);
}

