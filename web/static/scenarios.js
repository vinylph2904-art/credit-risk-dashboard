function initializeScenarios(root) {
  root.querySelectorAll('form[data-scenario]').forEach(form => {
    const container = form.closest('.dialog-body, .details-body');
    const output = container.querySelector('[data-scenario-output]');
    const error = container.querySelector('[data-scenario-error]');
    const submit = form.querySelector('button[type="submit"]');
    const mode = form.elements.namedItem('mode');
    const isPortfolio = form.dataset.scenario === 'portfolio';
    let controller;

    function clearResult() {
      controller?.abort();
      setLoadingState(output, false);
      output.hidden = true;
      error.hidden = true;
      submit.disabled = false;
    }
    function configure() {
      if (isPortfolio) {
        const fields = form.querySelector('[data-capacity-fields]');
        fields.hidden = mode.value !== 'capacity';
        fields.querySelectorAll('input,select').forEach(input => { input.disabled = fields.hidden; });
        form.querySelector('[data-portfolio-scope-note]').hidden =
          mode.value !== 'capacity' || form.elements.namedItem('scope').value !== 'portfolio';
      }
    }
    form.addEventListener('input', clearResult);
    form.addEventListener('change', () => { clearResult(); configure(); });
    form.addEventListener('reset', () => {
      clearResult();
      queueMicrotask(() => {
        configure();
        if (isPortfolio) form.querySelector('[data-threshold-range]').value = form.elements.threshold_percent.value;
      });
    });
    if (isPortfolio) {
      const number = form.elements.namedItem('threshold_percent');
      const range = form.querySelector('[data-threshold-range]');
      range.addEventListener('input', () => { number.value = range.value; });
      number.addEventListener('input', () => { range.value = number.value; });
      form.querySelectorAll('[data-scenario-threshold]').forEach(button => {
        button.addEventListener('click', () => {
          number.value = button.dataset.scenarioThreshold;
          range.value = number.value;
          clearResult();
        });
      });
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (isPortfolio && filtersHaveDraft()) { openReportFilters(); return; }
      clearResult();
      controller = new AbortController();
      const request = controller;
      const url = new URL(form.action, window.location.origin);
      const options = {signal: request.signal, headers: {Accept: 'text/html'}};
      if (isPortfolio) {
        url.search = window.location.search;
        if (form.dataset.operationalScope !== undefined) {
          const current = new URLSearchParams(window.location.search);
          url.search = '';
          ['product', 'income', 'amount_min', 'amount_max', 'age_min', 'age_max', 'availability'].forEach(name => {
            if (current.has(name)) url.searchParams.set(name, current.get(name));
          });
          url.searchParams.set('data_scope', 'managed');
        }
        url.searchParams.set('mode', mode.value);
        url.searchParams.set('threshold', String(Number(form.elements.threshold_percent.value) / 100));
        url.searchParams.set('scope', form.elements.scope.value);
        if (mode.value === 'capacity') url.searchParams.set('capacity', String(Number(form.elements.capacity.value)));
      } else {
        const names = ['AMT_INCOME_TOTAL', 'AMT_CREDIT', 'AMT_ANNUITY'];
        const changes = {};
        names.forEach(name => { changes[name] = Number(form.elements.namedItem(name).value); });
        options.method = 'POST';
        options.headers['Content-Type'] = 'application/json';
        options.headers['X-CSRF-Token'] = document.querySelector('meta[name="csrf-token"]').content;
        options.body = JSON.stringify({changes});
      }
      submit.disabled = true;
      output.hidden = false;
      setLoadingState(output, true, 'Đang tính mô phỏng…', 'Đang tổng hợp kết quả theo giả định bạn chọn…');
      try {
        const response = await fetch(url, options);
        if (response.status === 401) {
          window.location.assign('/login?next=' + encodeURIComponent(window.location.pathname + window.location.search));
          return;
        }
        if (!response.ok) {
          const payload = await response.json();
          throw new Error(payload.error || 'Không thể chạy mô phỏng.');
        }
        const html = await response.text();
        if (!request.signal.aborted && form.isConnected) output.innerHTML = html;
      } catch (failure) {
        if (failure.name !== 'AbortError' && form.isConnected) {
          output.hidden = true;
          error.textContent = failure.message;
          error.hidden = false;
        }
      } finally {
        if (controller === request) {
          setLoadingState(output, false);
          submit.disabled = false;
        }
      }
    });
    configure();
  });
}

