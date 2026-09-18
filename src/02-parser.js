/* Reading Visum exports in the browser: attribute files, CSV and GeoJSON. */
(function (TV) {
  'use strict';

  var SEPARATORS = [';', '\t', ','];
  var NUMBER_RE = /^[+-]?(?:\d[\d.,]*|[.,]\d+)(?:[eE][+-]?\d+)?/;
  var WKT_RE = /(?:MULTI)?LINESTRING\s*Z?\s*M?\s*\(/i;

  var ALIASES = {
    no: ['NO', 'LINKNO', 'LINK_NO', 'ID'],
    fromNode: ['FROMNODENO', 'FROM_NODE', 'FROMNODE', 'ANODE', 'NODEFROM'],
    toNode: ['TONODENO', 'TO_NODE', 'TONODE', 'BNODE', 'NODETO'],
    name: ['NAME', 'STREETNAME', 'LINKNAME', 'NAZEV'],
    typeNo: ['TYPENO', 'TYPE', 'LINKTYPE', 'TYP'],
    length: ['LENGTH', 'LEN', 'DELKA'],
    capacity: ['CAPPRT', 'CAPACITY', 'CAP', 'KAPACITA'],
    wkt: ['WKTPOLY', 'WKT', 'GEOMETRY', 'THE_GEOM'],
    xFrom: ['FROMNODE\\XCOORD', 'XCOORDFROM', 'FROMNODEXCOORD', 'XFROM', 'FROM_X', 'X1'],
    yFrom: ['FROMNODE\\YCOORD', 'YCOORDFROM', 'FROMNODEYCOORD', 'YFROM', 'FROM_Y', 'Y1'],
    xTo: ['TONODE\\XCOORD', 'XCOORDTO', 'TONODEXCOORD', 'XTO', 'TO_X', 'X2'],
    yTo: ['TONODE\\YCOORD', 'YCOORDTO', 'TONODEYCOORD', 'YTO', 'TO_Y', 'Y2']
  };

  function ImportError(message) {
    var error = new Error(message);
    error.name = 'ImportError';
    return error;
  }

  /** Decode a dropped file, guessing the encoding the way Visum writes them. */
  function decodeBuffer(buffer) {
    var bytes = new Uint8Array(buffer);
    if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
      return new TextDecoder('utf-8').decode(bytes.subarray(3));
    }
    try {
      return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch (e) {
      // Visum on Czech Windows writes cp1250.
      try {
        return new TextDecoder('windows-1250').decode(bytes);
      } catch (e2) {
        return new TextDecoder('iso-8859-1').decode(bytes);
      }
    }
  }

  function norm(name) {
    return String(name).replace(/[\s_]/g, '').toUpperCase();
  }

  function resolve(columns, role) {
    var lookup = {};
    columns.forEach(function (c) { lookup[norm(c)] = c; });
    var candidates = ALIASES[role];
    for (var i = 0; i < candidates.length; i += 1) {
      var hit = lookup[norm(candidates[i])];
      if (hit !== undefined) return hit;
    }
    return null;
  }

  function parseNumber(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === 'number') return isFinite(value) ? value : null;
    var text = String(value).trim().replace(/"/g, '');
    if (!text) return null;
    var match = NUMBER_RE.exec(text);
    if (!match) return null;
    var number = match[0].replace(/[.,]+$/, '');
    var mantissa = number;
    var exponent = '';
    var marker = number.search(/[eE]/);
    if (marker >= 0) {
      mantissa = number.slice(0, marker);
      exponent = number.slice(marker);
    }
    var lastDot = mantissa.lastIndexOf('.');
    var lastComma = mantissa.lastIndexOf(',');
    if (lastDot >= 0 && lastComma >= 0) {
      var at = Math.max(lastDot, lastComma);
      mantissa = mantissa.slice(0, at).replace(/[.,]/g, '') + '.'
        + mantissa.slice(at + 1).replace(/[.,]/g, '');
    } else {
      var separator = lastDot >= 0 ? '.' : (lastComma >= 0 ? ',' : '');
      if (separator) {
        var at2 = mantissa.lastIndexOf(separator);
        mantissa = mantissa.slice(0, at2).split(separator).join('') + '.' + mantissa.slice(at2 + 1);
      }
    }
    var result = parseFloat(mantissa + exponent);
    return isFinite(result) ? result : null;
  }

  function guessSeparator(header) {
    var body = header.indexOf(':') >= 0 ? header.slice(header.indexOf(':') + 1) : header;
    var best = ';';
    var bestCount = 0;
    SEPARATORS.forEach(function (sep) {
      var count = body.split(sep).length - 1;
      if (count > bestCount) { bestCount = count; best = sep; }
    });
    return bestCount ? best : ';';
  }

  /** Split a data row, honouring double quoted fields. */
  function splitRow(line, separator) {
    if (line.indexOf('"') < 0) {
      return line.split(separator).map(function (cell) { return cell.trim(); });
    }
    var out = [];
    var current = '';
    var inQuotes = false;
    for (var i = 0; i < line.length; i += 1) {
      var ch = line[i];
      if (ch === '"') {
        if (inQuotes && line[i + 1] === '"') { current += '"'; i += 1; continue; }
        inQuotes = !inQuotes;
      } else if (ch === separator && !inQuotes) {
        out.push(current.trim());
        current = '';
      } else {
        current += ch;
      }
    }
    out.push(current.trim());
    return out;
  }

  /** Parse an attribute file into its $TABLE blocks. */
  function parseAtt(text) {
    var tables = [];
    var current = null;
    var lines = text.split(/\r\n|\r|\n/);
    for (var i = 0; i < lines.length; i += 1) {
      var line = lines[i].replace(/^﻿/, '');
      var stripped = line.trim();
      if (!stripped || stripped[0] === '*') continue;
      if (stripped[0] === '$') {
        if (stripped.indexOf(':') < 0) { current = null; continue; }
        var at = stripped.indexOf(':');
        var head = stripped.slice(1, at).trim().toUpperCase();
        var separator = guessSeparator(stripped);
        var columns = stripped.slice(at + 1).split(separator)
          .map(function (c) { return c.trim().replace(/^"|"$/g, ''); })
          .filter(function (c) { return c.length > 0; });
        current = { name: head, columns: columns, rows: [], separator: separator };
        tables.push(current);
        continue;
      }
      if (!current) continue;
      var cells = splitRow(line, current.separator);
      var row = {};
      for (var c = 0; c < current.columns.length; c += 1) {
        row[current.columns[c]] = cells[c] === undefined ? '' : cells[c];
      }
      current.rows.push(row);
    }
    return tables;
  }

  function findTable(tables, names) {
    var wanted = names.map(function (n) { return n.toUpperCase(); });
    for (var i = 0; i < tables.length; i += 1) {
      if (wanted.indexOf(tables[i].name) >= 0) return tables[i];
    }
    return null;
  }

  function dedupe(points) {
    var out = [];
    for (var i = 0; i < points.length; i += 1) {
      var p = points[i];
      if (!out.length || Math.abs(p[0] - out[out.length - 1][0]) > 1e-9
          || Math.abs(p[1] - out[out.length - 1][1]) > 1e-9) {
        out.push([Number(p[0]), Number(p[1])]);
      }
    }
    return out;
  }

  function parseWkt(text) {
    if (!text) return [];
    var match = WKT_RE.exec(text);
    if (!match) return [];
    var body = text.slice(match.index + match[0].length - 1);
    var depth = 0;
    var end = body.length;
    for (var i = 0; i < body.length; i += 1) {
      if (body[i] === '(') depth += 1;
      else if (body[i] === ')') {
        depth -= 1;
        if (depth === 0) { end = i; break; }
      }
    }
    body = body.slice(1, end);
    var points = [];
    body.replace(/\(/g, ' ').replace(/\)/g, ',').split(',').forEach(function (chunk) {
      var parts = chunk.trim().split(/\s+/);
      if (parts.length >= 2) {
        var x = parseFloat(parts[0]);
        var y = parseFloat(parts[1]);
        if (isFinite(x) && isFinite(y)) points.push([x, y]);
      }
    });
    return dedupe(points);
  }

  function nodeCoordinates(tables) {
    var table = findTable(tables, ['NODE', 'NODES', 'KNOTEN']);
    if (!table) return {};
    var noCol = resolve(table.columns, 'no');
    var xCol = null;
    var yCol = null;
    table.columns.forEach(function (c) {
      if (norm(c) === 'XCOORD' || norm(c) === 'X') xCol = xCol || c;
      if (norm(c) === 'YCOORD' || norm(c) === 'Y') yCol = yCol || c;
    });
    if (!noCol || !xCol || !yCol) return {};
    var nodes = {};
    table.rows.forEach(function (row) {
      var x = parseNumber(row[xCol]);
      var y = parseNumber(row[yCol]);
      if (x === null || y === null) return;
      nodes[String(row[noCol]).trim()] = [x, y];
    });
    return nodes;
  }

  function linkPolylines(tables) {
    var table = findTable(tables, ['LINKPOLY', 'LINKPOLYGON']);
    if (!table) return {};
    var cols = {};
    table.columns.forEach(function (c) { cols[norm(c)] = c; });
    var linkCol = cols.LINKNO || cols.NO;
    var fromCol = cols.FROMNODENO;
    var toCol = cols.TONODENO;
    var indexCol = cols.INDEX || cols.IDX;
    var xCol = cols.XCOORD || cols.X;
    var yCol = cols.YCOORD || cols.Y;
    if (!linkCol || !fromCol || !toCol || !xCol || !yCol) return {};
    var buckets = {};
    table.rows.forEach(function (row, order) {
      var x = parseNumber(row[xCol]);
      var y = parseNumber(row[yCol]);
      if (x === null || y === null) return;
      var key = [String(row[linkCol]).trim(), String(row[fromCol]).trim(),
        String(row[toCol]).trim()].join('|');
      var index = indexCol ? parseNumber(row[indexCol]) : null;
      (buckets[key] = buckets[key] || []).push({
        order: index === null ? order : index, point: [x, y]
      });
    });
    var out = {};
    Object.keys(buckets).forEach(function (key) {
      out[key] = buckets[key]
        .sort(function (a, b) { return a.order - b.order; })
        .map(function (entry) { return entry.point; });
    });
    return out;
  }

  function rowsToLinks(rows, columns, nodes, polylines, warnings, wktColumn) {
    var noCol = resolve(columns, 'no');
    var fromCol = resolve(columns, 'fromNode');
    var toCol = resolve(columns, 'toNode');
    if (!noCol || !fromCol || !toCol) {
      throw ImportError(
        'Export musí obsahovat sloupce NO, FROMNODENO a TONODENO. Nalezeno: '
        + (columns.join(', ') || 'nic')
      );
    }
    var wktCol = wktColumn || resolve(columns, 'wkt');
    var xf = resolve(columns, 'xFrom');
    var yf = resolve(columns, 'yFrom');
    var xt = resolve(columns, 'xTo');
    var yt = resolve(columns, 'yTo');
    var nameCol = resolve(columns, 'name');
    var typeCol = resolve(columns, 'typeNo');
    var lengthCol = resolve(columns, 'length');
    var capCol = resolve(columns, 'capacity');

    var sources = {};
    var links = [];
    var skipped = 0;

    rows.forEach(function (row) {
      var linkNo = String(row[noCol] === undefined ? '' : row[noCol]).trim();
      var fromNode = String(row[fromCol] === undefined ? '' : row[fromCol]).trim();
      var toNode = String(row[toCol] === undefined ? '' : row[toCol]).trim();
      if (!linkNo || !fromNode || !toNode) { skipped += 1; return; }

      var geometry = [];
      var source = '';
      if (wktCol) {
        geometry = parseWkt(String(row[wktCol] || ''));
        source = 'WKTPOLY';
      }
      if (!geometry.length) {
        var start = nodes[fromNode];
        var end = nodes[toNode];
        var middle = polylines[[linkNo, fromNode, toNode].join('|')];
        if (!middle) {
          var reverse = polylines[[linkNo, toNode, fromNode].join('|')];
          middle = reverse ? reverse.slice().reverse() : [];
        }
        if (start && end) {
          geometry = dedupe([start].concat(middle, [end]));
          source = middle.length ? '$LINKPOLY' : '$NODE';
        }
      }
      if (!geometry.length && xf && yf && xt && yt) {
        var x1 = parseNumber(row[xf]);
        var y1 = parseNumber(row[yf]);
        var x2 = parseNumber(row[xt]);
        var y2 = parseNumber(row[yt]);
        if (x1 !== null && y1 !== null && x2 !== null && y2 !== null) {
          geometry = dedupe([[x1, y1], [x2, y2]]);
          source = 'souřadnice uzlů';
        }
      }
      if (geometry.length < 2) { skipped += 1; return; }
      sources[source] = (sources[source] || 0) + 1;

      var attrs = {};
      Object.keys(row).forEach(function (key) {
        if (key === wktCol || key === '__GEOM__') return;
        if (row[key] !== '' && row[key] !== null && row[key] !== undefined) attrs[key] = row[key];
      });

      links.push({
        linkNo: linkNo,
        fromNode: fromNode,
        toNode: toNode,
        key: linkNo + '|' + fromNode + '|' + toNode,
        geom: geometry,
        name: nameCol ? String(row[nameCol] || '').trim() : '',
        typeNo: typeCol ? String(row[typeCol] || '').trim() : '',
        length: lengthCol ? parseNumber(row[lengthCol]) : null,
        capacity: capCol ? parseNumber(row[capCol]) : null,
        attrs: attrs
      });
    });

    if (skipped) {
      warnings.push(skipped + ' řádků bylo přeskočeno, chybí jim geometrie nebo klíč.');
    }
    if (!links.length) {
      throw ImportError(
        'Nepodařilo se sestavit geometrii žádného linku. Exportujte linky včetně '
        + 'sloupce WKTPOLY, nebo uložte celou síť tak, aby obsahovala tabulku $NODE.'
      );
    }
    var geometrySource = Object.keys(sources).sort(function (a, b) {
      return sources[b] - sources[a];
    })[0] || 'neznámý';
    return { links: links, geometrySource: geometrySource };
  }

  function importAtt(text) {
    var tables = parseAtt(text);
    var linkTable = findTable(tables, ['LINK', 'LINKS', 'STRECKE', 'STRECKEN']);
    if (!linkTable) {
      var available = tables.map(function (t) { return t.name; }).join(', ') || 'žádné';
      throw ImportError('V souboru není tabulka $LINK (nalezené tabulky: ' + available + ').');
    }
    var warnings = [];
    var built = rowsToLinks(
      linkTable.rows, linkTable.columns, nodeCoordinates(tables), linkPolylines(tables), warnings
    );
    return {
      links: built.links,
      columns: linkTable.columns.slice(),
      warnings: warnings,
      geometrySource: built.geometrySource
    };
  }

  function importCsv(text) {
    var lines = text.split(/\r\n|\r|\n/).filter(function (line) {
      return line.trim() && line.trim()[0] !== '*';
    });
    if (!lines.length) throw ImportError('Soubor je prázdný.');
    var separator = guessSeparator(lines[0]);
    var columns = splitRow(lines[0], separator);
    var rows = [];
    for (var i = 1; i < lines.length; i += 1) {
      var cells = splitRow(lines[i], separator);
      var row = {};
      columns.forEach(function (column, index) {
        row[column] = cells[index] === undefined ? '' : cells[index];
      });
      rows.push(row);
    }
    var warnings = [];
    var built = rowsToLinks(rows, columns, {}, {}, warnings);
    return {
      links: built.links, columns: columns, warnings: warnings,
      geometrySource: built.geometrySource
    };
  }

  function importGeoJson(text) {
    var data = JSON.parse(text);
    if (!data || !data.features) throw ImportError('Soubor není GeoJSON FeatureCollection.');
    var rows = [];
    var columnSet = {};
    data.features.forEach(function (feature) {
      var geometry = (feature && feature.geometry) || {};
      var type = String(geometry.type || '').toLowerCase();
      var coords = geometry.coordinates || [];
      var points = [];
      if (type === 'linestring') {
        points = coords.filter(function (c) { return c.length >= 2; })
          .map(function (c) { return [Number(c[0]), Number(c[1])]; });
      } else if (type === 'multilinestring') {
        coords.forEach(function (part) {
          part.forEach(function (c) {
            if (c.length >= 2) points.push([Number(c[0]), Number(c[1])]);
          });
        });
      } else {
        return;
      }
      points = dedupe(points);
      if (points.length < 2) return;
      var row = Object.assign({}, feature.properties || {});
      Object.keys(row).forEach(function (key) { columnSet[key] = true; });
      row.__GEOM__ = 'LINESTRING(' + points.map(function (p) {
        return p[0] + ' ' + p[1];
      }).join(', ') + ')';
      rows.push(row);
    });
    if (!rows.length) throw ImportError('GeoJSON neobsahuje žádný LineString.');
    var columns = Object.keys(columnSet);
    var warnings = [];
    var built = rowsToLinks(rows, columns.concat(['__GEOM__']), {}, {}, warnings, '__GEOM__');
    return {
      links: built.links, columns: columns, warnings: warnings, geometrySource: 'GeoJSON'
    };
  }

  /** Pick the reader from the file name. */
  function importNetwork(fileName, text) {
    var suffix = (fileName.split('.').pop() || '').toLowerCase();
    if (suffix === 'att' || suffix === 'net' || suffix === 'txt') return importAtt(text);
    if (suffix === 'csv' || suffix === 'tsv') return importCsv(text);
    if (suffix === 'geojson' || suffix === 'json') return importGeoJson(text);
    throw ImportError(
      'Neznámý typ souboru ".' + suffix + '". Podporované: .att, .net, .csv, .geojson'
    );
  }

  /**
   * Make every geometry run from its own from-node to its own to-node.
   * Visum exports the same polyline for both directions, so the reverse one has
   * to be flipped before the map can offset it to the correct side.
   */
  function orientDirections(links) {
    var byLink = {};
    links.forEach(function (link) {
      (byLink[link.linkNo] = byLink[link.linkNo] || []).push(link);
    });
    Object.keys(byLink).forEach(function (linkNo) {
      var group = byLink[linkNo];
      var reference = group[0];
      for (var i = 1; i < group.length; i += 1) {
        var link = group[i];
        if (link.fromNode === reference.toNode && link.toNode === reference.fromNode) {
          var a = link.geom[0];
          var b = reference.geom[0];
          if (Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6) {
            link.geom = link.geom.slice().reverse();
          }
        }
      }
    });
    return links;
  }

  /** Read counted values back from a CSV or .att produced by this app. */
  function readValueRecords(fileName, text) {
    var suffix = (fileName.split('.').pop() || '').toLowerCase();
    var columns;
    var rows;
    if (suffix === 'att' || suffix === 'net' || suffix === 'txt') {
      var table = findTable(parseAtt(text), ['LINK', 'LINKS']);
      if (!table) throw ImportError('V souboru není tabulka $LINK.');
      columns = table.columns;
      rows = table.rows;
    } else {
      var lines = text.split(/\r\n|\r|\n/).filter(function (line) {
        return line.trim() && line.trim()[0] !== '*';
      });
      if (!lines.length) throw ImportError('Soubor je prázdný.');
      var separator = guessSeparator(lines[0]);
      columns = splitRow(lines[0].replace(/^﻿/, ''), separator);
      rows = lines.slice(1).map(function (line) {
        var cells = splitRow(line, separator);
        var row = {};
        columns.forEach(function (c, i) { row[c] = cells[i] === undefined ? '' : cells[i]; });
        return row;
      });
    }
    var noCol = resolve(columns, 'no');
    var fromCol = resolve(columns, 'fromNode');
    var toCol = resolve(columns, 'toNode');
    if (!noCol || !fromCol || !toCol) {
      throw ImportError('Soubor musí obsahovat sloupce NO, FROMNODENO a TONODENO.');
    }
    var skip = {};
    [noCol, fromCol, toCol].forEach(function (c) { skip[c] = true; });
    columns.forEach(function (c) {
      if (['NAME', 'NOTE', 'POZNAMKA', 'SURVEYOR', 'UPDATEDAT'].indexOf(norm(c)) >= 0) {
        skip[c] = true;
      }
    });
    var records = [];
    rows.forEach(function (row) {
      var linkNo = String(row[noCol] || '').trim();
      var fromNode = String(row[fromCol] || '').trim();
      var toNode = String(row[toCol] || '').trim();
      if (!linkNo || !fromNode || !toNode) return;
      var values = {};
      var any = false;
      columns.forEach(function (c) {
        if (skip[c]) return;
        var raw = String(row[c] === undefined ? '' : row[c]).trim();
        if (raw !== '') { values[c.toUpperCase()] = raw; any = true; }
      });
      if (any) records.push({ key: linkNo + '|' + fromNode + '|' + toNode, values: values });
    });
    return records;
  }

  TV.parser = {
    decodeBuffer: decodeBuffer,
    parseAtt: parseAtt,
    findTable: findTable,
    parseNumber: parseNumber,
    parseWkt: parseWkt,
    importAtt: importAtt,
    importCsv: importCsv,
    importGeoJson: importGeoJson,
    importNetwork: importNetwork,
    orientDirections: orientDirections,
    readValueRecords: readValueRecords,
    ImportError: ImportError
  };
})(typeof globalThis !== 'undefined'
  ? (globalThis.TV = globalThis.TV || {})
  : (this.TV = this.TV || {}));
