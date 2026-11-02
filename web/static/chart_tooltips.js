// Build the same safe tooltip markup for Plotly charts and SVG mini charts.
function createCompactChartTooltip(title, rows) {
  const tooltip = document.createElement('div');
  tooltip.className = 'compact-chart-tooltip';
  tooltip.setAttribute('role', 'tooltip');
  const heading = document.createElement('strong');
  heading.textContent = title;
  tooltip.append(heading);
  rows.forEach(([label, value]) => {
    const row = document.createElement('div');
    const key = document.createElement('span');
    const text = document.createElement('b');
    key.textContent = label;
    text.textContent = value;
    row.append(key, text);
    tooltip.append(row);
  });
  return tooltip;
}
