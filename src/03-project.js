/* Project state: the network, the values to collect and what has been typed in. */
(function (TV) {
  'use strict';

  var ATTR_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]{0,48}$/;

  var DEFAULT_FIELDS = [
    { name: 'VOL_MANUAL', label: 'Intenzita', valueType: 'int', unit: 'voz/den' }
  ];

  function normaliseField(field, position) {
    var name = String(field.name || '').trim().toUpperCase();
    if (!ATTR_NAME_RE.test(name)) {
      throw new Error(
        '"' + (field.name || '') + '" není platný název uživatelského atributu ve Visumu. '
        + 'Použijte písmena, číslice a podtržítko, začněte písmenem.'
      );
    }
    var valueType = field.valueType || 'int';
    if (['int', 'float', 'text'].indexOf(valueType) < 0) {
      throw new Error('Neznámý typ hodnoty "' + valueType + '".');
    }
    return {
      name: name,
      label: String(field.label || '').trim() || name,
      valueType: valueType,
      unit: String(field.unit || '').trim(),
      position: position
    };
  }

  /** Validate and normalise one value typed in by the surveyor. */
  function coerce(field, raw) {
    if (raw === null || raw === undefined) return null;
    var text = String(raw).trim();
    if (text === '') return null;
    if (field.valueType === 'text') return text;
    text = text.replace(/[\s ]/g, '').replace(',', '.');
    var number = parseFloat(text);
    if (!isFinite(number) || !/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(text)) {
      throw new Error(field.label + ': "' + raw + '" není číslo.');
    }
    if (field.valueType === 'int') {
      if (Math.abs(number - Math.round(number)) > 1e-9) {
        throw new Error(field.label + ': "' + raw + '" musí být celé číslo.');
      }
      return String(Math.round(number));
    }
    return String(number);
  }

  function Project(options) {
    this.id = options.id || ('tv-' + Date.now().toString(36) + '-'
      + Math.random().toString(36).slice(2, 8));
    this.name = options.name || 'Sčítání';
    this.crs = options.crs || 'LOCAL';
    this.coordMode = options.coordMode || 'local';
    this.source = options.source || '';
    this.createdAt = options.createdAt || new Date().toISOString();
    this.geometrySource = options.geometrySource || '';
    this.fields = (options.fields || DEFAULT_FIELDS).map(normaliseField);
    this.links = options.links || [];
    this.entries = options.entries || {};   // key -> {values, note, status, surveyor, updatedAt}
    this.history = options.history || [];
    this.surveyor = options.surveyor || '';
    this.byKey = {};
    var self = this;
    this.links.forEach(function (link) { self.byKey[link.key] = link; });
    this._reverseCache = null;
  }

  Project.prototype.field = function (name) {
    var upper = String(name).toUpperCase();
    for (var i = 0; i < this.fields.length; i += 1) {
      if (this.fields[i].name === upper) return this.fields[i];
    }
    return null;
  };

  Project.prototype.primaryField = function () {
    return this.fields.length ? this.fields[0].name : null;
  };

  Project.prototype.entry = function (key) {
    return this.entries[key] || { values: {}, note: '', status: 'empty', surveyor: '', updatedAt: null };
  };

  Project.prototype.valuesOf = function (key) {
    return this.entry(key).values || {};
  };

  Project.prototype.numericValue = function (key, fieldName) {
    var raw = this.valuesOf(key)[fieldName || this.primaryField()];
    if (raw === undefined || raw === null || raw === '') return null;
    var number = parseFloat(String(raw).replace(',', '.'));
    return isFinite(number) ? number : null;
  };

  Project.prototype.reverseKey = function (key) {
    if (!this._reverseCache) {
      var cache = {};
      this.links.forEach(function (link) {
        var reverse = link.linkNo + '|' + link.toNode + '|' + link.fromNode;
        cache[link.key] = reverse;
      });
      this._reverseCache = cache;
    }
    var candidate = this._reverseCache[key];
    return candidate && this.byKey[candidate] ? candidate : null;
  };

  /** Store the values for one direction and record the change. */
  Project.prototype.setValues = function (key, rawValues, options) {
    var settings = options || {};
    if (!this.byKey[key]) throw new Error('Směr linku "' + key + '" není součástí projektu.');

    var self = this;
    var cleaned = {};
    Object.keys(rawValues).forEach(function (name) {
      var field = self.field(name);
      if (!field) throw new Error('Neznámá veličina "' + name + '".');
      cleaned[field.name] = coerce(field, rawValues[name]);
    });

    var entry = this.entries[key];
    var previous = (entry && entry.values) || {};
    var values = Object.assign({}, previous);
    var timestamp = new Date().toISOString();
    var surveyor = settings.surveyor === undefined ? this.surveyor : settings.surveyor;
    var changed = false;

    Object.keys(cleaned).forEach(function (name) {
      var next = cleaned[name];
      var before = previous[name] === undefined ? null : previous[name];
      if (before === next) return;
      changed = true;
      if (next === null) delete values[name];
      else values[name] = next;
      self.history.push({
        key: key, field: name, from: before, to: next, surveyor: surveyor, ts: timestamp
      });
    });
    if (self.history.length > 5000) self.history.splice(0, self.history.length - 5000);

    var hasValue = Object.keys(values).some(function (name) {
      return values[name] !== null && values[name] !== '';
    });
    var note = settings.note === undefined ? ((entry && entry.note) || '') : String(settings.note);
    var status = settings.status
      || (hasValue ? 'filled' : (note ? 'noted' : 'empty'));

    if (status === 'empty' && !note) {
      delete this.entries[key];
    } else {
      this.entries[key] = {
        values: values, note: note, status: status,
        surveyor: surveyor, updatedAt: timestamp
      };
    }
    return { changed: changed, entry: this.entry(key) };
  };

  Project.prototype.clearValues = function (key, options) {
    var blank = {};
    this.fields.forEach(function (field) { blank[field.name] = null; });
    return this.setValues(key, blank, Object.assign({ note: '', status: 'empty' }, options || {}));
  };

  Project.prototype.stats = function () {
    var total = this.links.length;
    var filled = 0;
    var flagged = 0;
    var self = this;
    Object.keys(this.entries).forEach(function (key) {
      var entry = self.entries[key];
      var has = Object.keys(entry.values || {}).some(function (name) {
        return entry.values[name] !== null && entry.values[name] !== '';
      });
      if (has) filled += 1;
      if (entry.status === 'flagged') flagged += 1;
    });
    return { total: total, filled: filled, flagged: flagged, remaining: total - filled };
  };

  Project.prototype.bounds = function () {
    if (!this.links.length) return null;
    var minx = Infinity;
    var miny = Infinity;
    var maxx = -Infinity;
    var maxy = -Infinity;
    this.links.forEach(function (link) {
      link.geom.forEach(function (p) {
        if (p[0] < minx) minx = p[0];
        if (p[1] < miny) miny = p[1];
        if (p[0] > maxx) maxx = p[0];
        if (p[1] > maxy) maxy = p[1];
      });
    });
    return [minx, miny, maxx, maxy];
  };

  /** Merge values coming from a CSV, an .att or another saved session. */
  Project.prototype.importRecords = function (records, options) {
    var settings = options || {};
    var updated = 0;
    var missing = 0;
    var self = this;
    records.forEach(function (record) {
      if (!self.byKey[record.key]) { missing += 1; return; }
      if (settings.keepExisting) {
        var existing = self.valuesOf(record.key);
        var hasValue = Object.keys(existing).some(function (name) {
          return existing[name] !== null && existing[name] !== '';
        });
        if (hasValue) return;
      }
      var accepted = {};
      Object.keys(record.values).forEach(function (name) {
        if (self.field(name)) accepted[name] = record.values[name];
      });
      if (!Object.keys(accepted).length) return;
      self.setValues(record.key, accepted, { surveyor: settings.surveyor || 'import' });
      updated += 1;
    });
    return { updated: updated, missing: missing };
  };

  /** Everything needed to restore this project later, as plain JSON. */
  Project.prototype.toJSON = function () {
    return {
      format: 'trafficvolumes/1',
      id: this.id,
      name: this.name,
      crs: this.crs,
      coordMode: this.coordMode,
      source: this.source,
      createdAt: this.createdAt,
      geometrySource: this.geometrySource,
      surveyor: this.surveyor,
      fields: this.fields,
      links: this.links,
      entries: this.entries,
      history: this.history
    };
  };

  Project.fromJSON = function (data) {
    if (!data || data.format !== 'trafficvolumes/1') {
      throw new Error('Soubor neobsahuje uloženou práci z této aplikace.');
    }
    return new Project(data);
  };

  /** Build a project from a freshly imported network. */
  Project.fromImport = function (imported, settings) {
    var options = settings || {};
    var crs = options.crs;
    if (!crs || crs === 'auto') {
      crs = TV.projection.detectCrs(imported.links.slice(0, 500).map(function (link) {
        return link.geom[0];
      }));
    }
    var projector = TV.projection.getProjector(crs);
    var links = TV.parser.orientDirections(imported.links);
    var kept = [];
    links.forEach(function (link) {
      var geom = [];
      for (var i = 0; i < link.geom.length; i += 1) {
        var p = projector.fn(link.geom[i][0], link.geom[i][1]);
        if (!isFinite(p[0]) || !isFinite(p[1])) return;
        geom.push([Math.round(p[0] * 1e7) / 1e7, Math.round(p[1] * 1e7) / 1e7]);
      }
      if (geom.length < 2) return;
      link.geom = geom;
      kept.push(link);
    });
    if (!kept.length) {
      throw new Error('Po převodu souřadnic nezbyl žádný link. Zkontrolujte souřadnicový systém.');
    }
    // Duplicate direction keys would make two map features share one value.
    var seen = {};
    var unique = kept.filter(function (link) {
      if (seen[link.key]) return false;
      seen[link.key] = true;
      return true;
    });
    return new Project({
      name: options.name || 'Sčítání',
      crs: projector.crs,
      coordMode: projector.mode,
      source: options.source || '',
      geometrySource: imported.geometrySource,
      fields: options.fields || DEFAULT_FIELDS,
      links: unique
    });
  };

  TV.Project = Project;
  TV.projectHelpers = {
    DEFAULT_FIELDS: DEFAULT_FIELDS,
    normaliseField: normaliseField,
    coerce: coerce,
    ATTR_NAME_RE: ATTR_NAME_RE
  };
})(typeof globalThis !== 'undefined'
  ? (globalThis.TV = globalThis.TV || {})
  : (this.TV = this.TV || {}));
