/* Application wiring: loading files, the entry form, exports and autosave. */
(function (TV) {
  'use strict';

  var BASEMAP_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  var BASEMAP_ATTRIBUTION =
    '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">'
    + 'OpenStreetMap</a> přispěvatelé';

  var $ = function (id) { return document.getElementById(id); };

  var state = {
    project: null,
    map: null,
    selected: null,
    pendingImport: null,
    fieldRows: 0
  };

  /* ---------- small helpers ---------- */

  var toastTimer = null;
  function toast(message, isError) {
    var element = $('toast');
    element.textContent = message;
    element.classList.toggle('error', !!isError);
    element.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      element.classList.add('hidden');
    }, isError ? 7000 : 2200);
  }

  function message(text, kind) {
    var box = $('start-message');
    if (!text) { box.innerHTML = ''; return; }
    box.innerHTML = '';
    var note = document.createElement('div');
    note.className = 'note' + (kind ? ' ' + kind : '');
    note.textContent = text;
    box.appendChild(note);
  }

  function formatTime(iso) {
    if (!iso) return '';
    var date = new Date(iso);
    if (isNaN(date.getTime())) return iso;
    return date.toLocaleString('cs-CZ', {
      day: 'numeric', month: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  }

  function readFile(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(reader.error); };
      reader.readAsArrayBuffer(file);
    });
  }

  /* ---------- loading files ---------- */

  /** Pull the embedded project out of a previously saved HTML file. */
  function extractEmbedded(text) {
    var match = /<script[^>]+id=["']tv-embedded["'][^>]*>([\s\S]*?)<\/script>/i.exec(text);
    if (!match) return null;
    return JSON.parse(match[1]);
  }

  function handleFile(file) {
    message('');
    return readFile(file).then(function (buffer) {
      var text = TV.parser.decodeBuffer(buffer);
      var suffix = (file.name.split('.').pop() || '').toLowerCase();

      if (suffix === 'html' || suffix === 'htm') {
        var embedded = extractEmbedded(text);
        if (!embedded) throw new Error('V tomto HTML souboru není uložená žádná práce.');
        openProject(TV.Project.fromJSON(embedded));
        return;
      }
      if (suffix === 'json') {
        var data = JSON.parse(text);
        if (data && data.format === 'trafficvolumes/1') {
          openProject(TV.Project.fromJSON(data));
          return;
        }
        // Otherwise it is probably GeoJSON, so fall through to the importer.
      }
      var imported = TV.parser.importNetwork(file.name, text);
      showSetup(imported, file.name);
    }).catch(function (error) {
      message(error.message || String(error), 'error');
    });
  }

  /* ---------- setup screen ---------- */

  function showSetup(imported, fileName) {
    state.pendingImport = { imported: imported, fileName: fileName };

    var select = $('setup-crs');
    select.innerHTML = '';
    var detected = TV.projection.detectCrs(imported.links.slice(0, 500).map(function (link) {
      return link.geom[0];
    }));
    TV.projection.CRS_LIST.forEach(function (crs) {
      var option = document.createElement('option');
      option.value = crs.id;
      option.textContent = crs.id === 'auto'
        ? crs.label + ' (rozpoznáno: ' + detected + ')'
        : crs.label;
      select.appendChild(option);
    });
    select.value = 'auto';

    $('setup-name').value = fileName.replace(/\.[^.]+$/, '');
    $('setup-summary').textContent =
      imported.links.length + ' směrů linků · geometrie z ' + imported.geometrySource
      + (imported.warnings.length ? ' · ' + imported.warnings.join(' ') : '');

    $('setup-fields').innerHTML = '';
    state.fieldRows = 0;
    TV.projectHelpers.DEFAULT_FIELDS.forEach(addFieldRow);

    $('setup').classList.remove('hidden');
    $('setup').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function addFieldRow(field) {
    var data = field || { name: '', label: '', valueType: 'int', unit: '' };
    var row = document.createElement('div');
    row.className = 'row';
    row.innerHTML =
      '<label class="field"><span>Název atributu</span>'
      + '<input type="text" data-role="name" placeholder="VOL_MANUAL"></label>'
      + '<label class="field"><span>Popisek</span>'
      + '<input type="text" data-role="label" placeholder="Intenzita"></label>'
      + '<label class="field shrink"><span>Typ</span><select data-role="type">'
      + '<option value="int">celé číslo</option>'
      + '<option value="float">desetinné</option>'
      + '<option value="text">text</option></select></label>'
      + '<label class="field shrink"><span>Jednotka</span>'
      + '<input type="text" data-role="unit" placeholder="voz/den"></label>';

    row.querySelector('[data-role=name]').value = data.name;
    row.querySelector('[data-role=label]').value = data.label;
    row.querySelector('[data-role=type]').value = data.valueType;
    row.querySelector('[data-role=unit]').value = data.unit;

    var remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'icon';
    remove.textContent = '✕';
    remove.title = 'Odebrat veličinu';
    remove.addEventListener('click', function () {
      if ($('setup-fields').children.length <= 1) {
        message('Projekt musí mít alespoň jednu veličinu.', 'warn');
        return;
      }
      row.remove();
    });
    row.appendChild(remove);
    $('setup-fields').appendChild(row);
    state.fieldRows += 1;
  }

  function collectFields() {
    var fields = [];
    var rows = $('setup-fields').querySelectorAll('.row');
    for (var i = 0; i < rows.length; i += 1) {
      var row = rows[i];
      var name = row.querySelector('[data-role=name]').value.trim();
      if (!name) continue;
      fields.push({
        name: name,
        label: row.querySelector('[data-role=label]').value.trim(),
        valueType: row.querySelector('[data-role=type]').value,
        unit: row.querySelector('[data-role=unit]').value.trim()
      });
    }
    if (!fields.length) throw new Error('Zadejte alespoň jednu veličinu.');
    var seen = {};
    fields.forEach(function (field) {
      var key = field.name.toUpperCase();
      if (seen[key]) throw new Error('Veličina "' + key + '" je uvedená dvakrát.');
      seen[key] = true;
    });
    return fields;
  }

  function createProject() {
    try {
      var fields = collectFields();
      var project = TV.Project.fromImport(state.pendingImport.imported, {
        name: $('setup-name').value.trim() || 'Sčítání',
        crs: $('setup-crs').value,
        source: state.pendingImport.fileName,
        fields: fields
      });
      state.pendingImport = null;
      $('setup').classList.add('hidden');
      openProject(project);
    } catch (error) {
      message(error.message || String(error), 'error');
    }
  }

  /* ---------- recent sessions ---------- */

  function renderRecent() {
    return TV.autosave.list().then(function (rows) {
      var container = $('recent');
      container.innerHTML = '';
      if (!rows.length) {
        $('recent-block').classList.add('hidden');
        return;
      }
      $('recent-block').classList.remove('hidden');
      rows.slice(0, 6).forEach(function (row) {
        var element = document.createElement('div');
        element.className = 'recent-row';
        var info = document.createElement('div');
        info.className = 'grow';
        info.innerHTML = '<b></b><span class="muted small"></span>';
        info.querySelector('b').textContent = row.name || 'Projekt';
        info.querySelector('span').textContent =
          row.total + ' směrů · uloženo ' + formatTime(row.savedAt);
        element.appendChild(info);

        var open = document.createElement('button');
        open.type = 'button';
        open.className = 'primary';
        open.textContent = 'Pokračovat';
        open.addEventListener('click', function () {
          TV.autosave.load(row.id).then(function (data) {
            if (!data) { message('Uloženou práci se nepodařilo načíst.', 'error'); return; }
            openProject(TV.Project.fromJSON(data));
          }).catch(function (error) { message(String(error), 'error'); });
        });
        element.appendChild(open);

        var drop = document.createElement('button');
        drop.type = 'button';
        drop.className = 'icon';
        drop.textContent = '✕';
        drop.title = 'Odstranit z prohlížeče';
        drop.addEventListener('click', function () {
          if (!window.confirm('Opravdu smazat uloženou práci "' + row.name + '"?')) return;
          TV.autosave.remove(row.id).then(renderRecent);
        });
        element.appendChild(drop);
        container.appendChild(element);
      });
    });
  }

  /* ---------- work screen ---------- */

  function openProject(project) {
    TV.fileSink.forget();
    $('btn-file-sink').textContent = 'Průběžně ukládat do souboru…';
    state.project = project;
    state.selected = null;
    $('start').classList.add('hidden');
    $('work').classList.remove('hidden');

    document.title = project.name + ' — TrafficVolumes';
    $('project-name').textContent = project.name;
    $('project-meta').textContent = [
      project.crs === 'LOCAL' ? 'místní souřadnice' : project.crs,
      project.source,
      project.links.length + ' směrů'
    ].filter(Boolean).join(' · ');
    $('surveyor').value = project.surveyor || '';

    if (!state.map) {
      state.map = new TV.TrafficMap($('map'), {
        onSelect: function (link) {
          if (link) showLink(link.key);
          else hideDetail();
        }
      });
    }
    state.map.setProject(project);
    state.map.resize();
    state.map.fitBounds(project.bounds());

    $('basemap-toggle').classList.toggle('hidden', project.coordMode !== 'geographic');
    $('attribution').innerHTML = '';
    $('show-basemap').checked = false;
    state.map.setBasemap(BASEMAP_URL, false);

    buildValueInputs();
    renderLegend();
    hideDetail();
    updateProgress();
    updateSaveState();
    save();
  }

  function buildValueInputs() {
    var container = $('value-inputs');
    container.innerHTML = '';
    state.project.fields.forEach(function (field) {
      var label = document.createElement('label');
      label.className = 'field';
      var caption = document.createElement('span');
      caption.textContent = field.label + (field.unit ? ' [' + field.unit + ']' : '');
      var input = document.createElement('input');
      input.id = 'value-' + field.name;
      input.dataset.field = field.name;
      input.autocomplete = 'off';
      input.type = 'text';
      if (field.valueType !== 'text') {
        // Deliberately not type="number": that silently discards "12,5" typed
        // with a Czech decimal comma, and its native validation bubble would
        // pre-empt the app's own, clearer message. Values go through the
        // project's own check instead, which also accepts "12 500".
        input.inputMode = field.valueType === 'int' ? 'numeric' : 'decimal';
        input.placeholder = field.valueType === 'int' ? 'např. 12500' : 'např. 12,5';
      }
      label.appendChild(caption);
      label.appendChild(input);
      container.appendChild(label);
    });
  }

  function renderLegend() {
    var colours = TV.mapColours;
    var html = '<span class="swatch" style="background:' + colours.EMPTY
      + '"></span>nevyplněno · ';
    colours.RAMP.forEach(function (colour) {
      html += '<span class="swatch" style="background:' + colour + '"></span>';
    });
    html += ' nízká → vysoká · <span class="swatch" style="background:' + colours.FLAGGED
      + '"></span>k prověření';
    $('legend').innerHTML = html;
  }

  function hideDetail() {
    state.selected = null;
    $('detail').classList.add('hidden');
    $('placeholder').classList.remove('hidden');
  }

  function showLink(key, options) {
    var settings = options || {};
    var project = state.project;
    var link = project.byKey[key];
    if (!link) return;
    state.selected = link;
    $('placeholder').classList.add('hidden');
    $('detail').classList.remove('hidden');

    var entry = project.entry(key);
    $('detail-title').textContent =
      'Link ' + link.linkNo + '  (' + link.fromNode + ' → ' + link.toNode + ')';
    var bits = [];
    if (link.name) bits.push(link.name);
    if (link.typeNo) bits.push('typ ' + link.typeNo);
    if (link.length !== null && link.length !== undefined) bits.push(link.length + ' km');
    if (link.capacity) bits.push('kapacita ' + link.capacity);
    $('detail-sub').textContent = bits.join(' · ');

    project.fields.forEach(function (field) {
      var input = $('value-' + field.name);
      if (input) input.value = entry.values[field.name] === undefined ? '' : entry.values[field.name];
    });
    $('note').value = entry.note || '';
    $('flagged').checked = entry.status === 'flagged';

    var reverse = project.reverseKey(key);
    $('btn-opposite').disabled = !reverse;
    $('btn-copy').disabled = !reverse;

    var attrs = $('attrs-list');
    attrs.innerHTML = '';
    Object.keys(link.attrs || {}).forEach(function (name) {
      var dt = document.createElement('dt');
      dt.textContent = name;
      var dd = document.createElement('dd');
      dd.textContent = link.attrs[name];
      attrs.appendChild(dt);
      attrs.appendChild(dd);
    });

    renderHistory(key);
    state.map.select(key, !!settings.centre);
    if (settings.focus !== false) {
      var first = $('value-inputs').querySelector('input');
      if (first) { first.focus(); first.select(); }
    }
  }

  function renderHistory(key) {
    var list = $('history-list');
    list.innerHTML = '';
    var rows = state.project.history.filter(function (row) {
      return row.key === key;
    }).slice(-25).reverse();
    if (!rows.length) {
      list.innerHTML = '<li>zatím bez změn</li>';
      return;
    }
    rows.forEach(function (row) {
      var item = document.createElement('li');
      item.textContent = formatTime(row.ts) + ' — ' + row.field + ': '
        + (row.from === null ? '—' : row.from) + ' → ' + (row.to === null ? '—' : row.to)
        + (row.surveyor ? ' (' + row.surveyor + ')' : '');
      list.appendChild(item);
    });
  }

  function collectValues() {
    var values = {};
    state.project.fields.forEach(function (field) {
      var input = $('value-' + field.name);
      values[field.name] = input ? input.value : '';
    });
    return values;
  }

  function updateProgress() {
    var stats = state.project.stats();
    var percent = stats.total ? Math.round((stats.filled / stats.total) * 100) : 0;
    $('progress-fill').style.width = percent + '%';
    $('progress-text').textContent =
      stats.filled + ' z ' + stats.total + ' směrů vyplněno (' + percent + ' %)'
      + (stats.flagged ? ' · ' + stats.flagged + ' označeno' : '');
  }

  function updateSaveState(error) {
    var element = $('save-state');
    var sink = TV.fileSink;
    var parts = [];
    var failed = !!error || !!sink.lastError;

    if (error) {
      parts.push('Ukládání do prohlížeče selhalo: ' + error.message);
    } else if (TV.autosave.lastSavedAt) {
      parts.push('V prohlížeči uloženo ' + formatTime(TV.autosave.lastSavedAt));
    } else {
      parts.push('Automatické ukládání připraveno');
    }

    if (sink.handle) {
      if (sink.lastError) {
        parts.push('zápis do ' + sink.fileName + ' selhal: ' + sink.lastError.message);
      } else if (sink.lastWrittenAt) {
        parts.push('soubor ' + sink.fileName + ' aktualizován ' + formatTime(sink.lastWrittenAt));
      } else {
        parts.push('soubor ' + sink.fileName + ' připraven');
      }
    }
    if (failed) parts.push('uložte práci tlačítkem výše');
    element.classList.toggle('error', failed);
    element.textContent = parts.join(' · ') + '.';
  }

  function save() {
    TV.autosave.scheduleSave(state.project, function (error) {
      updateSaveState(error);
    });
    TV.fileSink.schedule(function () {
      return TV.exporters.toStandaloneHtml(state.project);
    }, function () {
      updateSaveState(TV.autosave.lastError);
    });
  }

  function chooseSinkFile() {
    TV.fileSink.choose(TV.exporters.slug(state.project.name) + '.html')
      .then(function (name) {
        $('btn-file-sink').textContent = 'Ukládá se do: ' + name;
        toast('Práce se teď průběžně zapisuje do ' + name + '.');
        return TV.fileSink.schedule(function () {
          return TV.exporters.toStandaloneHtml(state.project);
        }, function () { updateSaveState(TV.autosave.lastError); });
      })
      .catch(function (error) {
        if (error && error.name === 'AbortError') return;   // the picker was closed
        toast(error.message || String(error), true);
      });
  }

  function saveCurrent() {
    if (!state.selected) return false;
    var project = state.project;
    try {
      project.surveyor = $('surveyor').value.trim();
      project.setValues(state.selected.key, collectValues(), {
        note: $('note').value,
        status: $('flagged').checked ? 'flagged' : undefined,
        surveyor: project.surveyor
      });
    } catch (error) {
      toast(error.message || String(error), true);
      return false;
    }
    state.map.refresh(state.selected.key);
    renderHistory(state.selected.key);
    updateProgress();
    save();
    toast('Uloženo.');
    return true;
  }

  function clearCurrent() {
    if (!state.selected) return;
    state.project.clearValues(state.selected.key, {
      surveyor: $('surveyor').value.trim()
    });
    state.map.refresh(state.selected.key);
    showLink(state.selected.key, { focus: false });
    updateProgress();
    save();
    toast('Hodnoty vymazány.');
  }

  function copyToOpposite() {
    if (!state.selected) return;
    var reverse = state.project.reverseKey(state.selected.key);
    if (!reverse) return;
    if (!saveCurrent()) return;
    try {
      state.project.setValues(reverse, collectValues(), {
        surveyor: $('surveyor').value.trim()
      });
    } catch (error) {
      toast(error.message || String(error), true);
      return;
    }
    state.map.refresh(reverse);
    updateProgress();
    save();
    toast('Zkopírováno do opačného směru.');
  }

  function nextEmpty() {
    var map = state.map;
    var candidates = map.items.filter(function (item) {
      return item.value === null && (!state.selected || item.key !== state.selected.key);
    });
    if (!candidates.length) {
      toast('Všechny směry jsou vyplněné.');
      return;
    }
    var centre = map.centre;
    candidates.sort(function (a, b) {
      return Math.hypot(a.bbox[0] - centre[0], a.bbox[1] - centre[1])
        - Math.hypot(b.bbox[0] - centre[0], b.bbox[1] - centre[1]);
    });
    showLink(candidates[0].key, { centre: true });
  }

  function applySearch() {
    var needle = $('search').value.trim().toLowerCase();
    if (!needle) {
      state.map.setFilter(null);
      return;
    }
    var keys = {};
    var matches = 0;
    state.project.links.forEach(function (link) {
      var haystack = [link.linkNo, link.fromNode, link.toNode, link.name]
        .join(' ').toLowerCase();
      if (haystack.indexOf(needle) >= 0) { keys[link.key] = true; matches += 1; }
    });
    state.map.setFilter(matches ? keys : {});
    if (!matches) {
      toast('Nic nenalezeno.');
    } else {
      var bounds = state.project.links.reduce(function (acc, link) {
        if (!keys[link.key]) return acc;
        link.geom.forEach(function (p) {
          acc[0] = Math.min(acc[0], p[0]);
          acc[1] = Math.min(acc[1], p[1]);
          acc[2] = Math.max(acc[2], p[0]);
          acc[3] = Math.max(acc[3], p[1]);
        });
        return acc;
      }, [Infinity, Infinity, -Infinity, -Infinity]);
      state.map.fitBounds(bounds);
      toast(matches + ' nalezeno.');
    }
  }

  /* ---------- exports ---------- */

  function includeEmpty() { return $('include-empty').checked; }

  function exportPng() {
    var project = state.project;
    var stats = project.stats();
    var canvas = state.map.exportImage({
      title: project.name,
      subtitle: stats.filled + ' z ' + stats.total + ' směrů vyplněno'
        + (project.fields.length ? ' · ' + project.fields[0].label : ''),
      footerRight: new Date().toLocaleDateString('cs-CZ')
    });
    TV.exporters.downloadPng(canvas, project);
  }

  function mergeValues(file) {
    readFile(file).then(function (buffer) {
      var text = TV.parser.decodeBuffer(buffer);
      var suffix = (file.name.split('.').pop() || '').toLowerCase();
      var records;
      if (suffix === 'html' || suffix === 'htm' || suffix === 'json') {
        var data = suffix === 'json' ? JSON.parse(text) : extractEmbedded(text);
        if (!data) throw new Error('V souboru není uložená práce.');
        records = Object.keys(data.entries || {}).map(function (key) {
          return { key: key, values: data.entries[key].values || {} };
        });
      } else {
        records = TV.parser.readValueRecords(file.name, text);
      }
      var result = state.project.importRecords(records, { surveyor: file.name });
      state.map.setProject(state.project);
      state.map.draw();
      updateProgress();
      save();
      toast(result.updated + ' směrů převzato'
        + (result.missing ? ', ' + result.missing + ' nenalezeno v této síti' : '') + '.');
    }).catch(function (error) {
      toast(error.message || String(error), true);
    });
  }

  /* ---------- wiring ---------- */

  function wire() {
    var dropzone = $('dropzone');
    var fileInput = $('file-input');

    $('btn-browse').addEventListener('click', function (event) {
      event.stopPropagation();
      fileInput.click();
    });
    dropzone.addEventListener('click', function () { fileInput.click(); });
    fileInput.addEventListener('change', function () {
      if (fileInput.files[0]) handleFile(fileInput.files[0]);
      fileInput.value = '';
    });

    ['dragenter', 'dragover'].forEach(function (type) {
      dropzone.addEventListener(type, function (event) {
        event.preventDefault();
        dropzone.classList.add('over');
      });
    });
    ['dragleave', 'drop'].forEach(function (type) {
      dropzone.addEventListener(type, function (event) {
        event.preventDefault();
        dropzone.classList.remove('over');
      });
    });
    dropzone.addEventListener('drop', function (event) {
      var file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) handleFile(file);
    });
    // Dropping anywhere on the start screen works too.
    $('start').addEventListener('dragover', function (event) { event.preventDefault(); });
    $('start').addEventListener('drop', function (event) {
      event.preventDefault();
      var file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) handleFile(file);
    });

    $('btn-add-field').addEventListener('click', function () { addFieldRow(null); });
    $('btn-create').addEventListener('click', createProject);
    $('btn-cancel-setup').addEventListener('click', function () {
      state.pendingImport = null;
      $('setup').classList.add('hidden');
      message('');
    });

    $('value-form').addEventListener('submit', function (event) {
      event.preventDefault();
      saveCurrent();
    });
    $('btn-clear').addEventListener('click', clearCurrent);
    $('btn-copy').addEventListener('click', copyToOpposite);
    $('btn-next').addEventListener('click', nextEmpty);
    $('btn-opposite').addEventListener('click', function () {
      if (!state.selected) return;
      var reverse = state.project.reverseKey(state.selected.key);
      if (reverse) showLink(reverse);
    });

    $('surveyor').addEventListener('change', function () {
      state.project.surveyor = $('surveyor').value.trim();
      save();
    });
    $('search').addEventListener('change', applySearch);
    $('search').addEventListener('search', applySearch);

    $('show-labels').addEventListener('change', function (event) {
      state.map.showLabels = event.target.checked;
      state.map.draw();
    });
    $('show-bands').addEventListener('change', function (event) {
      state.map.showBands = event.target.checked;
      state.map.draw();
    });
    $('show-arrows').addEventListener('change', function (event) {
      state.map.showArrows = event.target.checked;
      state.map.draw();
    });
    $('show-basemap').addEventListener('change', function (event) {
      state.map.setBasemap(BASEMAP_URL, event.target.checked);
      $('attribution').innerHTML = event.target.checked ? BASEMAP_ATTRIBUTION : '';
    });

    $('zoom-in').addEventListener('click', function () { state.map.zoomBy(1.6); });
    $('zoom-out').addEventListener('click', function () { state.map.zoomBy(1 / 1.6); });
    $('zoom-fit').addEventListener('click', function () {
      state.map.fitBounds(state.project.bounds());
    });

    $('btn-file-sink').addEventListener('click', chooseSinkFile);
    $('btn-file-sink').disabled = !TV.fileSink.supported;
    if (!TV.fileSink.supported) {
      $('btn-file-sink').title =
        'Průběžný zápis do souboru umí Chrome a Edge. V jiném prohlížeči '
        + 'použijte tlačítko "Uložit práci (HTML)".';
    }

    $('btn-save-html').addEventListener('click', function () {
      TV.exporters.downloadStandalone(state.project);
      toast('Uloženo jako samostatný HTML soubor.');
    });
    $('btn-csv').addEventListener('click', function () {
      TV.exporters.downloadCsv(state.project, includeEmpty());
    });
    $('btn-att').addEventListener('click', function () {
      TV.exporters.downloadAtt(state.project, includeEmpty());
    });
    $('btn-png').addEventListener('click', exportPng);
    $('btn-geojson').addEventListener('click', function () {
      try {
        TV.exporters.downloadGeoJson(state.project);
      } catch (error) {
        toast(error.message, true);
      }
    });
    $('btn-script').addEventListener('click', function () {
      TV.exporters.downloadVisumScript(state.project);
    });
    $('btn-merge').addEventListener('click', function () { $('merge-input').click(); });
    $('merge-input').addEventListener('change', function () {
      var file = $('merge-input').files[0];
      if (file) mergeValues(file);
      $('merge-input').value = '';
    });

    $('btn-back').addEventListener('click', function () {
      if (!window.confirm(
        'Zavřít projekt? Práce zůstane uložená v prohlížeči a najdete ji v seznamu.'
      )) return;
      $('work').classList.add('hidden');
      $('start').classList.remove('hidden');
      document.title = 'TrafficVolumes — zadávání intenzit';
      renderRecent();
    });

    document.addEventListener('keydown', function (event) {
      if ($('work').classList.contains('hidden')) return;
      var typing = ['INPUT', 'TEXTAREA', 'SELECT'].indexOf(event.target.tagName) >= 0;
      if (event.key === 'Escape') {
        state.map.select(null);
        hideDetail();
        return;
      }
      if (typing) return;
      var key = event.key.toLowerCase();
      if (key === 'n') { event.preventDefault(); nextEmpty(); }
      if (key === 'o' && state.selected) {
        var reverse = state.project.reverseKey(state.selected.key);
        if (reverse) { event.preventDefault(); showLink(reverse); }
      }
    });

    window.addEventListener('beforeunload', function (event) {
      if (state.project && (TV.autosave.lastError || TV.fileSink.lastError)) {
        event.preventDefault();
        event.returnValue = '';
      }
    });
  }

  /* ---------- boot ---------- */

  function boot() {
    wire();
    // A file saved with "Uložit práci" carries its project inside it.
    var embedded = document.getElementById('tv-embedded');
    if (embedded && embedded.textContent.trim()) {
      try {
        openProject(TV.Project.fromJSON(JSON.parse(embedded.textContent)));
        return;
      } catch (error) {
        message('Vložená data se nepodařilo načíst: ' + error.message, 'error');
      }
    }
    $('work').classList.add('hidden');
    $('start').classList.remove('hidden');
    renderRecent();

    var fallback = TV.autosave.fallbackEntries();
    if (fallback) {
      message(
        'Minule se nepodařilo uložit práci do prohlížeče. Zadané hodnoty ('
        + Object.keys(fallback.entries || {}).length + ' směrů) jsou zachované — '
        + 'načtěte znovu síť a použijte "Načíst hodnoty…".',
        'warn'
      );
    }
  }

  TV.ui = { boot: boot, state: state };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(typeof globalThis !== 'undefined'
  ? (globalThis.TV = globalThis.TV || {})
  : (this.TV = this.TV || {}));
