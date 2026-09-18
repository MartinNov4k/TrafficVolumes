/* Everything the surveyor can hand back: CSV, a Visum attribute file, GeoJSON,
 * a PNG of the volume plot and a self contained HTML file that carries the
 * whole project inside it. */
(function (TV) {
  'use strict';

  var DIACRITICS = {
    'á': 'a', 'č': 'c', 'ď': 'd', 'é': 'e', 'ě': 'e', 'í': 'i', 'ň': 'n', 'ó': 'o',
    'ř': 'r', 'š': 's', 'ť': 't', 'ú': 'u', 'ů': 'u', 'ý': 'y', 'ž': 'z',
    'Á': 'A', 'Č': 'C', 'Ď': 'D', 'É': 'E', 'Ě': 'E', 'Í': 'I', 'Ň': 'N', 'Ó': 'O',
    'Ř': 'R', 'Š': 'S', 'Ť': 'T', 'Ú': 'U', 'Ů': 'U', 'Ý': 'Y', 'Ž': 'Z'
  };

  /** Visum reads attribute files as cp1250; keeping them ASCII avoids the issue. */
  function toAscii(text) {
    return String(text === null || text === undefined ? '' : text).replace(
      /[^\x00-\x7F]/g,
      function (ch) { return DIACRITICS[ch] !== undefined ? DIACRITICS[ch] : '?'; }
    );
  }

  function slug(text) {
    var ascii = toAscii(text).replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '');
    return ascii || 'export';
  }

  function formatValue(field, raw) {
    if (raw === null || raw === undefined || raw === '') return '';
    if (field.valueType === 'text') return String(raw);
    var number = TV.parser.parseNumber(raw);
    if (number === null) return '';
    if (field.valueType === 'int') return String(Math.round(number));
    return String(Math.round(number * 1e6) / 1e6);
  }

  function quoteCsv(value, separator) {
    var text = value === null || value === undefined ? '' : String(value);
    if (text.indexOf(separator) >= 0 || text.indexOf('"') >= 0 || /[\r\n]/.test(text)) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
  }

  /** Directions in Visum key order, optionally including the untouched ones. */
  function rowsOf(project, includeEmpty) {
    var rows = project.links.slice().sort(function (a, b) {
      var na = parseInt(a.linkNo, 10);
      var nb = parseInt(b.linkNo, 10);
      if (isFinite(na) && isFinite(nb) && na !== nb) return na - nb;
      if (a.linkNo !== b.linkNo) return a.linkNo < b.linkNo ? -1 : 1;
      return a.fromNode < b.fromNode ? -1 : (a.fromNode > b.fromNode ? 1 : 0);
    });
    if (includeEmpty) return rows;
    return rows.filter(function (link) {
      var values = project.valuesOf(link.key);
      return Object.keys(values).some(function (name) {
        return values[name] !== null && values[name] !== '';
      });
    });
  }

  function toCsv(project, options) {
    var settings = options || {};
    var separator = settings.separator || ';';
    var lines = [];
    var header = ['NO', 'FROMNODENO', 'TONODENO', 'NAME']
      .concat(project.fields.map(function (f) { return f.name; }))
      .concat(['NOTE', 'SURVEYOR', 'UPDATED_AT']);
    lines.push(header.join(separator));
    rowsOf(project, settings.includeEmpty).forEach(function (link) {
      var entry = project.entry(link.key);
      var cells = [link.linkNo, link.fromNode, link.toNode, link.name]
        .concat(project.fields.map(function (field) {
          return formatValue(field, entry.values[field.name]);
        }))
        .concat([entry.note || '', entry.surveyor || '', entry.updatedAt || '']);
      lines.push(cells.map(function (cell) {
        return quoteCsv(cell, separator);
      }).join(separator));
    });
    return lines.join('\r\n') + '\r\n';
  }

  function attTypeName(valueType) {
    return { int: 'Integer', float: 'Double', text: 'Text' }[valueType] || 'Text';
  }

  function toAtt(project, options) {
    var settings = options || {};
    var stats = project.stats();
    var lines = ['$VISION'];
    var comments = [
      'Traffic volumes entered manually with TrafficVolumes',
      'Project    : ' + toAscii(project.name),
      'Source net : ' + toAscii(project.source),
      'Exported   : ' + new Date().toISOString().slice(0, 19).replace('T', ' '),
      'Directions : ' + stats.filled + ' filled of ' + stats.total,
      '',
      'Before reading this file, create the user defined attributes on the link',
      'network object, using exactly these IDs and types:'
    ];
    project.fields.forEach(function (field) {
      comments.push('  ' + field.name + '  ' + attTypeName(field.valueType)
        + (field.unit ? ' [' + toAscii(field.unit) + ']' : '')
        + '  -- ' + toAscii(field.label));
    });
    comments.push('');
    comments.push('Then read this file as an attribute file. The key columns');
    comments.push('NO;FROMNODENO;TONODENO address one direction of each link, so');
    comments.push('both directions keep their own value.');
    comments.forEach(function (comment) { lines.push('* ' + comment); });
    lines.push('*');
    lines.push('$LINK:NO;FROMNODENO;TONODENO;'
      + project.fields.map(function (f) { return f.name; }).join(';'));

    rowsOf(project, settings.includeEmpty).forEach(function (link) {
      var values = project.valuesOf(link.key);
      var cells = [link.linkNo, link.fromNode, link.toNode].concat(
        project.fields.map(function (field) {
          return toAscii(formatValue(field, values[field.name]));
        })
      );
      lines.push(cells.join(';'));
    });
    return lines.join('\r\n') + '\r\n';
  }

  function toGeoJson(project) {
    if (project.coordMode !== 'geographic') {
      throw new Error(
        'GeoJSON potřebuje zeměpisné souřadnice, tento projekt používá místní systém.'
      );
    }
    var features = project.links.map(function (link) {
      var entry = project.entry(link.key);
      var properties = {
        NO: link.linkNo, FROMNODENO: link.fromNode, TONODENO: link.toNode,
        NAME: link.name, NOTE: entry.note || '', STATUS: entry.status
      };
      project.fields.forEach(function (field) {
        properties[field.name] = entry.values[field.name] === undefined
          ? null : entry.values[field.name];
      });
      return {
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: link.geom },
        properties: properties
      };
    });
    return JSON.stringify({ type: 'FeatureCollection', features: features }, null, 1);
  }

  /** A ready to run script for the Visum side of the workflow. */
  function visumScript(project, attFileName) {
    var codes = { int: 1, float: 2, text: 5 };
    var rows = project.fields.map(function (field) {
      return '    ("' + field.name + '", "' + toAscii(field.label) + '", '
        + codes[field.valueType] + ')';
    }).join(',\n');
    return [
      '"""Create the user attributes and read the counted volumes into Visum.',
      '',
      'Run from Visum\'s Python console (Scripts > Run script file...), or from an',
      'external Python with win32com installed. Needs a Visum licence; the person',
      'collecting the data does not.',
      '"""',
      '',
      'import os',
      '',
      'try:                      # inside Visum the object already exists',
      '    Visum',
      'except NameError:         # outside Visum, attach to a running instance',
      '    import win32com.client',
      '    Visum = win32com.client.Dispatch("Visum.Visum")',
      '',
      '# Put the exported file next to this script, or set the full path here.',
      'ATT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '
        + '"' + attFileName + '")',
      '',
      '# Visum COM ValueType codes: 1 = Int, 2 = Real (Double), 5 = Text.',
      '# Check them against the COM help of your Visum version if a call fails.',
      'ATTRIBUTES = [',
      rows,
      ']',
      '',
      'existing = {a.AttributeID.upper() for a in Visum.Net.Links.Attributes.GetAll}',
      'for att_id, label, value_type in ATTRIBUTES:',
      '    if att_id.upper() in existing:',
      '        print("user attribute %s already exists" % att_id)',
      '        continue',
      '    Visum.Net.Links.AddUserDefinedAttribute(att_id, att_id, label, value_type)',
      '    print("created user attribute %s" % att_id)',
      '',
      'if not os.path.isfile(ATT_FILE):',
      '    raise SystemExit("attribute file not found: %s" % ATT_FILE)',
      '',
      'Visum.LoadAttributeFile(ATT_FILE)',
      'print("read %s" % ATT_FILE)',
      ''
    ].join('\n');
  }

  /**
   * Serialise the running page together with the project data.
   *
   * The app is a single file with inline scripts, so the live DOM already holds
   * the whole application; embedding the project as JSON next to it produces a
   * file that reopens exactly where the work stopped.
   */
  function toStandaloneHtml(project) {
    var clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('[data-dynamic]').forEach(function (node) {
      node.innerHTML = '';
    });
    var stale = clone.querySelector('#tv-embedded');
    if (stale) stale.parentNode.removeChild(stale);

    var script = document.createElement('script');
    script.id = 'tv-embedded';
    script.type = 'application/json';
    // Escaping "<" keeps the JSON from ever closing the script element early.
    script.textContent = JSON.stringify(project.toJSON()).replace(/</g, '\\u003c');
    clone.querySelector('head').appendChild(script);
    return '<!DOCTYPE html>\n' + clone.outerHTML;
  }

  function download(fileName, content, mimeType) {
    var blob = content instanceof Blob
      ? content
      : new Blob([content], { type: mimeType || 'application/octet-stream' });
    var url = URL.createObjectURL(blob);
    var anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }

  var Exporters = {
    toAscii: toAscii,
    slug: slug,
    toCsv: toCsv,
    toAtt: toAtt,
    toGeoJson: toGeoJson,
    visumScript: visumScript,
    toStandaloneHtml: toStandaloneHtml,
    download: download,
    formatValue: formatValue,
    rowsOf: rowsOf,

    downloadCsv: function (project, includeEmpty) {
      // The BOM makes Excel open the semicolon separated file in columns.
      download(slug(project.name) + '.csv', '﻿' + toCsv(project, {
        includeEmpty: includeEmpty
      }), 'text/csv;charset=utf-8');
    },

    downloadAtt: function (project, includeEmpty) {
      download(slug(project.name) + '.att', toAtt(project, { includeEmpty: includeEmpty }),
        'text/plain;charset=us-ascii');
    },

    downloadGeoJson: function (project) {
      download(slug(project.name) + '.geojson', toGeoJson(project),
        'application/geo+json;charset=utf-8');
    },

    downloadVisumScript: function (project) {
      download('nacti_do_visumu.py', visumScript(project, slug(project.name) + '.att'),
        'text/x-python;charset=utf-8');
    },

    downloadStandalone: function (project) {
      download(slug(project.name) + '.html', toStandaloneHtml(project),
        'text/html;charset=utf-8');
    },

    downloadPng: function (canvas, project) {
      canvas.toBlob(function (blob) {
        download(slug(project.name) + '_kartogram.png', blob, 'image/png');
      }, 'image/png');
    }
  };

  TV.exporters = Exporters;
})(typeof globalThis !== 'undefined'
  ? (globalThis.TV = globalThis.TV || {})
  : (this.TV = this.TV || {}));
