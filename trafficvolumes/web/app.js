/* UI wiring: project metadata, the entry form, filters and exports. */
'use strict';

(function () {
  const token = new URLSearchParams(location.search).get('t') || '';
  const $ = (id) => document.getElementById(id);

  const state = {
    project: null,
    fields: [],
    selected: null,
    loadByViewport: false,
    loading: false,
    pendingReload: null,
  };

  /* -- API ----------------------------------------------------------------- */

  async function api(path, options) {
    const config = Object.assign({ headers: {} }, options || {});
    config.headers = Object.assign({}, config.headers);
    if (token) config.headers['X-Auth-Token'] = token;
    if (config.body !== undefined) {
      config.headers['Content-Type'] = 'application/json';
      config.body = JSON.stringify(config.body);
    }
    const response = await fetch(path, config);
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch (e) { payload = null; }
    if (!response.ok) {
      throw new Error((payload && payload.error) || response.statusText || 'Chyba serveru');
    }
    return payload;
  }

  function exportHref(kind, params) {
    const query = new URLSearchParams(params || {});
    if (token) query.set('t', token);
    const suffix = query.toString();
    return '/api/export/' + kind + (suffix ? '?' + suffix : '');
  }

  /* -- toast --------------------------------------------------------------- */

  let toastTimer = null;
  function toast(message, isError) {
    const element = $('toast');
    element.textContent = message;
    element.classList.toggle('error', !!isError);
    element.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => element.classList.add('hidden'), isError ? 6000 : 2200);
  }

  /* -- map ----------------------------------------------------------------- */

  let map = null;

  function primaryField() {
    return state.fields.length ? state.fields[0].name : null;
  }

  async function loadLinks(bounds) {
    if (state.loading) {
      state.pendingReload = bounds;
      return;
    }
    state.loading = true;
    try {
      const params = new URLSearchParams();
      if (bounds && state.loadByViewport) params.set('bbox', bounds.map((v) => v.toFixed(7)).join(','));
      if ($('search').value.trim()) params.set('search', $('search').value.trim());
      if ($('filter-empty').checked) params.set('only_empty', '1');
      if ($('filter-flagged').checked) params.set('only_flagged', '1');
      const data = await api('/api/links?' + params.toString());
      map.setData(data.links, primaryField());
      map.draw();
      if (data.truncated) {
        toast('Zobrazeno prvních ' + data.count + ' směrů, přibližte mapu nebo zúžte filtr.', true);
      }
    } catch (error) {
      toast(error.message, true);
    } finally {
      state.loading = false;
      const pending = state.pendingReload;
      state.pendingReload = null;
      if (pending !== null) loadLinks(pending);
    }
  }

  const debouncedLoad = debounce((bounds) => {
    if (state.loadByViewport) loadLinks(bounds);
  }, 250);

  function debounce(fn, delay) {
    let timer = null;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(null, args), delay);
    };
  }

  /* -- detail panel -------------------------------------------------------- */

  function buildForm() {
    const container = $('value-inputs');
    container.innerHTML = '';
    for (const field of state.fields) {
      const label = document.createElement('label');
      label.className = 'field';
      const caption = document.createElement('span');
      caption.textContent = field.label + (field.unit ? ' [' + field.unit + ']' : '') +
        (field.required ? ' *' : '');
      const input = document.createElement('input');
      input.id = 'value-' + field.name;
      input.dataset.field = field.name;
      input.autocomplete = 'off';
      if (field.value_type === 'text') {
        input.type = 'text';
      } else {
        input.type = 'number';
        input.step = field.value_type === 'int' ? '1' : 'any';
        input.min = '0';
        input.inputMode = field.value_type === 'int' ? 'numeric' : 'decimal';
      }
      label.appendChild(caption);
      label.appendChild(input);
      container.appendChild(label);
    }
  }

  async function showLink(link, options) {
    state.selected = link;
    $('placeholder').classList.add('hidden');
    $('detail').classList.remove('hidden');

    const direction = link.from_node + ' → ' + link.to_node;
    $('detail-title').textContent = 'Link ' + link.link_no + '  (' + direction + ')';
    const bits = [];
    if (link.name) bits.push(link.name);
    if (link.type_no) bits.push('typ ' + link.type_no);
    if (link.length !== null && link.length !== undefined) bits.push(link.length + ' km');
    if (link.capacity) bits.push('kapacita ' + link.capacity);
    $('detail-sub').textContent = bits.join(' · ');

    for (const field of state.fields) {
      const input = $('value-' + field.name);
      if (input) input.value = link.values[field.name] !== undefined ? link.values[field.name] : '';
    }
    $('note').value = link.note || '';
    $('flagged').checked = link.status === 'flagged';
    $('btn-opposite').disabled = !link.reverse_key;
    $('btn-copy').disabled = !link.reverse_key;

    const attrs = $('attrs-list');
    attrs.innerHTML = '';
    for (const [key, value] of Object.entries(link.attrs || {})) {
      const dt = document.createElement('dt');
      dt.textContent = key;
      const dd = document.createElement('dd');
      dd.textContent = value;
      attrs.appendChild(dt);
      attrs.appendChild(dd);
    }

    map.select(link.key, options && options.centre);
    if (!options || options.focus !== false) {
      const first = $('value-inputs').querySelector('input');
      if (first) { first.focus(); first.select(); }
    }
    loadHistory(link.key);
  }

  async function loadHistory(key) {
    const list = $('history-list');
    list.innerHTML = '<li>…</li>';
    try {
      const data = await api('/api/link/' + encodeURIComponent(key) + '/history');
      list.innerHTML = '';
      if (!data.history.length) {
        list.innerHTML = '<li>zatím bez změn</li>';
        return;
      }
      for (const row of data.history) {
        const item = document.createElement('li');
        const when = row.ts ? row.ts.replace('T', ' ').replace('+00:00', ' UTC') : '';
        item.textContent = when + ' — ' + row.field + ': ' +
          (row.old_value === null ? '—' : row.old_value) + ' → ' +
          (row.new_value === null ? '—' : row.new_value) +
          (row.surveyor ? ' (' + row.surveyor + ')' : '');
        list.appendChild(item);
      }
    } catch (error) {
      list.innerHTML = '<li>' + error.message + '</li>';
    }
  }

  async function selectByKey(key, options) {
    try {
      const link = await api('/api/link/' + encodeURIComponent(key));
      await showLink(link, options);
    } catch (error) {
      toast(error.message, true);
    }
  }

  function collectValues() {
    const values = {};
    for (const field of state.fields) {
      const input = $('value-' + field.name);
      values[field.name] = input ? input.value : '';
    }
    return values;
  }

  async function save() {
    if (!state.selected) return;
    const link = state.selected;
    try {
      const updated = await api('/api/link/' + encodeURIComponent(link.key), {
        method: 'POST',
        body: {
          values: collectValues(),
          note: $('note').value,
          status: $('flagged').checked ? 'flagged' : undefined,
          surveyor: $('surveyor').value.trim(),
        },
      });
      localStorage.setItem('tvol.surveyor', $('surveyor').value.trim());
      map.updateLink(updated);
      state.selected = updated;
      await refreshStats();
      toast('Uloženo.');
      return updated;
    } catch (error) {
      toast(error.message, true);
      return null;
    }
  }

  async function clearValues() {
    if (!state.selected) return;
    try {
      const updated = await api(
        '/api/link/' + encodeURIComponent(state.selected.key), { method: 'DELETE' }
      );
      map.updateLink(updated);
      await showLink(await api('/api/link/' + encodeURIComponent(updated.key)), { focus: false });
      await refreshStats();
      toast('Hodnoty vymazány.');
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function copyToOpposite() {
    if (!state.selected || !state.selected.reverse_key) return;
    const saved = await save();
    if (!saved) return;
    try {
      const updated = await api('/api/link/' + encodeURIComponent(state.selected.reverse_key), {
        method: 'POST',
        body: { values: collectValues(), surveyor: $('surveyor').value.trim() },
      });
      map.updateLink(updated);
      await refreshStats();
      toast('Zkopírováno do opačného směru.');
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function nextEmpty() {
    const field = primaryField();
    const candidates = (map.items || []).filter((item) => item.value === null);
    if (!candidates.length) {
      toast('Ve stažené části sítě už není nevyplněný směr.');
      return;
    }
    const centre = map.centre;
    candidates.sort((a, b) => {
      const da = Math.hypot(a.bbox[0] - centre[0], a.bbox[1] - centre[1]);
      const db = Math.hypot(b.bbox[0] - centre[0], b.bbox[1] - centre[1]);
      return da - db;
    });
    const target = candidates.find((item) => !state.selected || item.key !== state.selected.key);
    if (target) await selectByKey(target.key, { centre: true });
  }

  async function refreshStats() {
    try {
      const stats = await api('/api/stats');
      const percent = stats.total ? Math.round((stats.filled / stats.total) * 100) : 0;
      $('progress-fill').style.width = percent + '%';
      $('progress-text').textContent =
        stats.filled + ' z ' + stats.total + ' směrů vyplněno (' + percent + ' %)' +
        (stats.flagged ? ' · ' + stats.flagged + ' označeno' : '');
    } catch (error) {
      /* stats are cosmetic, stay quiet */
    }
  }

  /* -- boot ---------------------------------------------------------------- */

  async function boot() {
    let project;
    try {
      project = await api('/api/project');
    } catch (error) {
      document.body.innerHTML =
        '<p style="padding:24px">Nepodařilo se načíst projekt: ' + error.message + '</p>';
      return;
    }
    state.project = project;
    state.fields = project.fields;

    $('project-name').textContent = project.name || 'TrafficVolumes';
    $('project-meta').textContent =
      [project.crs, project.source].filter(Boolean).join(' · ');
    $('surveyor').value = localStorage.getItem('tvol.surveyor') || '';

    map = new TrafficMap($('map'), {
      geographic: project.coord_mode === 'geographic',
      onSelect: (link) => {
        if (link) selectByKey(link.key);
        else {
          state.selected = null;
          $('detail').classList.add('hidden');
          $('placeholder').classList.remove('hidden');
        }
      },
      onViewChange: (bounds) => debouncedLoad(bounds),
    });
    // Exposed so that automated UI checks can hit-test the canvas.
    window.__tvolMap = map;

    if (project.basemap && project.coord_mode === 'geographic') {
      $('show-basemap').closest('label').classList.remove('hidden');
      $('attribution').innerHTML = project.basemap_attribution || '';
    } else {
      $('show-basemap').closest('label').classList.add('hidden');
    }

    buildForm();
    // Large networks are streamed per viewport; small ones stay in memory.
    state.loadByViewport = project.stats.total > 15000;
    if (project.bounds) map.fitBounds(project.bounds);
    await loadLinks(map.viewBounds());
    await refreshStats();

    $('legend').innerHTML =
      '<span class="swatch" style="background:' + window.trafficMapHelpers.COLOR_EMPTY +
      '"></span>nevyplněno · ' +
      window.trafficMapHelpers.RAMP.map(
        (c) => '<span class="swatch" style="background:' + c + '"></span>'
      ).join('') + ' nízká → vysoká intenzita · ' +
      '<span class="swatch" style="background:' + window.trafficMapHelpers.COLOR_FLAGGED +
      '"></span>k prověření';

    if (project.read_only) {
      toast('Server běží v režimu jen pro čtení, změny se neuloží.', true);
    }
    wireControls();
  }

  function wireControls() {
    $('value-form').addEventListener('submit', (event) => {
      event.preventDefault();
      save();
    });
    $('btn-clear').addEventListener('click', clearValues);
    $('btn-copy').addEventListener('click', copyToOpposite);
    $('btn-next').addEventListener('click', nextEmpty);
    $('btn-opposite').addEventListener('click', () => {
      if (state.selected && state.selected.reverse_key) {
        selectByKey(state.selected.reverse_key);
      }
    });

    $('search').addEventListener('input', debounce(() => loadLinks(map.viewBounds()), 300));
    for (const id of ['filter-empty', 'filter-flagged']) {
      $(id).addEventListener('change', () => loadLinks(map.viewBounds()));
    }
    $('show-labels').addEventListener('change', (event) => {
      map.showLabels = event.target.checked;
      map.draw();
    });
    $('show-bands').addEventListener('change', (event) => {
      map.showBands = event.target.checked;
      map.draw();
    });
    $('show-basemap').addEventListener('change', (event) => {
      map.setBasemap(state.project.basemap, event.target.checked);
    });

    $('zoom-in').addEventListener('click', () => map.zoomBy(1.6));
    $('zoom-out').addEventListener('click', () => map.zoomBy(1 / 1.6));
    $('zoom-fit').addEventListener('click', () => map.fitBounds(state.project.bounds));

    $('export-att').href = exportHref('att');
    $('export-csv').href = exportHref('csv');
    $('export-geojson').href = exportHref('geojson');
    $('export-script').href = exportHref('visum-script');

    document.addEventListener('keydown', (event) => {
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName);
      if (event.key === 'Escape') {
        map.select(null);
        state.selected = null;
        $('detail').classList.add('hidden');
        $('placeholder').classList.remove('hidden');
        return;
      }
      if (typing && event.key !== 'Enter') return;
      if (event.key === 'Enter' && typing) return;  // handled by the form
      const key = event.key.toLowerCase();
      if (key === 'n') { event.preventDefault(); nextEmpty(); }
      if (key === 'o' && state.selected && state.selected.reverse_key) {
        event.preventDefault();
        selectByKey(state.selected.reverse_key);
      }
    });
  }

  boot();
})();
