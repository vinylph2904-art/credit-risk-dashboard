(() => {
  const charts = new WeakMap();
  let active, tooltip;
  function clear() {
    active?.svg.classList.remove('has-mini-focus');
    active?.mark.classList.remove('is-mini-active');
    active?.svg.removeAttribute('aria-describedby');
    if (active?.cardTitle != null) active.card.setAttribute('title', active.cardTitle);
    tooltip?.remove();
    active = tooltip = null;
  }
  function prepare(svg) {
    if (!charts.has(svg)) {
      svg.setAttribute('aria-description', svg.querySelector('title')?.textContent || '');
      const points = [...svg.querySelectorAll('[data-kpi-point]')].map(mark => {
        const text = mark.querySelector('title')?.textContent || '';
        mark.setAttribute('aria-label', text);
        const separator = text.indexOf(':');
        return {mark, name: text.slice(0, separator), values: text.slice(separator + 1).trim().split(' · ')};
      });
      svg.querySelectorAll('title').forEach(title => title.remove());
      charts.set(svg, points);
    }
    return charts.get(svg);
  }
  function position(x, y) {
    const box = tooltip.getBoundingClientRect(), gap = 12;
    tooltip.style.left = `${Math.max(gap, Math.min(x + gap, window.innerWidth - box.width - gap))}px`;
    tooltip.style.top = `${Math.max(gap, Math.min(y + gap, window.innerHeight - box.height - gap))}px`;
  }
  function show(svg, point, x, y) {
    if (active?.mark !== point.mark) {
      clear();
      const card = svg.closest('.kpi'), cardTitle = card?.getAttribute('title');
      active = {svg, mark: point.mark, card, cardTitle};
      card?.removeAttribute('title');
      svg.classList.add('has-mini-focus');
      point.mark.classList.add('is-mini-active');
      const donut = svg.closest('[data-mini-kind]').dataset.miniKind === 'donut';
      const rows = point.values.map((value, index) => {
        let label = '';
        if (index === 0) label = donut ? 'Tỷ trọng' : 'Giá trị';
        else if (donut && index === 1) label = 'Giá trị';
        return [label, value];
      });
      tooltip = createCompactChartTooltip(point.name, rows);
      tooltip.classList.add('kpi-mini-tooltip');
      tooltip.id = 'kpi-mini-tooltip';
      document.body.append(tooltip);
      svg.setAttribute('aria-describedby', tooltip.id);
    }
    position(x, y);
  }
  document.addEventListener('pointermove', event => {
    const svg = event.target.closest?.('.kpi-mini-chart svg');
    if (!svg) { clear(); return; }
    const points = prepare(svg);
    let point;
    if (svg.closest('[data-mini-kind]').dataset.miniKind === 'donut') {
      const box = svg.getBoundingClientRect();
      const dx = (event.clientX - box.left) / box.width * 40 - 20;
      const dy = (event.clientY - box.top) / box.height * 40 - 20;
      const radius = Math.hypot(dx, dy);
      if (radius >= 11 && radius <= 19) {
        const angle = ((Math.atan2(dy, dx) + Math.PI / 2 + 2 * Math.PI) % (2 * Math.PI)) / (2 * Math.PI);
        let end = 0;
        point = points.find(item => { end += Number(item.mark.dataset.share); return angle < end; });
      }
    } else {
      const mark = event.target.closest('[data-kpi-point]');
      point = points.find(item => item.mark === mark);
    }
    if (point) show(svg, point, event.clientX, event.clientY); else clear();
  });
  document.addEventListener('focusin', event => {
    const svg = event.target.closest?.('.kpi-mini-chart svg');
    if (!svg) return;
    const point = prepare(svg)[0], box = svg.getBoundingClientRect();
    if (point) show(svg, point, box.right, box.top);
  });
  document.addEventListener('keydown', event => {
    const svg = event.target.closest?.('.kpi-mini-chart svg');
    if (!svg) return;
    if (event.key === 'Escape') { clear(); return; }
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const points = prepare(svg);
    if (!points.length) return;
    const index = points.findIndex(point => point.mark === active?.mark);
    const step = ['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1;
    const point = points[(index + step + points.length) % points.length], box = svg.getBoundingClientRect();
    show(svg, point, box.right, box.top);
  });
  document.addEventListener('focusout', clear);
  document.addEventListener('scroll', clear, true);
  window.addEventListener('resize', clear);
  window.addEventListener('blur', clear);
  document.addEventListener('pointerout', event => { if (!event.relatedTarget) clear(); });
})();
