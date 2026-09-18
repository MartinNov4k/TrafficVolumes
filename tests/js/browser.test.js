/* Unit tests for the logic that does not need a DOM.
 * Run with: node --test tests/js/
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');

const SRC = path.join(__dirname, '..', '..', 'src');
globalThis.TV = {};
['01-projection.js', '02-parser.js', '03-project.js', '05-export.js']
  .forEach((name) => require(path.join(SRC, name)));
const TV = globalThis.TV;

/* ---------------- projection ---------------- */

test('Krovak reproduces the EPSG 9819 worked example', () => {
  const [lon, lat] = TV.projection.krovakToBessel(1050538.63, 568991.00);
  // The published point is rounded to 0.0001", so a metre is all it can show;
  // in practice we land within a few centimetres.
  assert.ok(Math.abs(lat - 50.20901222) * 111320 < 0.2, `lat off: ${lat}`);
  assert.ok(Math.abs(lon - 16.84977194) * 71500 < 0.2, `lon off: ${lon}`);
});

test('the datum shift brings us onto WGS84 like PROJ does', () => {
  const [lon, lat] = TV.projection.krovakToWgs84(1050538.63, 568991.00);
  assert.ok(Math.abs(lat - 50.2082971) < 1e-5, `lat ${lat}`);
  assert.ok(Math.abs(lon - 16.8483268) < 1e-5, `lon ${lon}`);
});

test('EPSG:5514 uses the east-north axis order', () => {
  const [lon, lat] = TV.projection.getProjector('epsg:5514').fn(-742000, -1043000);
  assert.ok(Math.abs(lat - 50.0885718) < 1e-5, `lat ${lat}`);
  assert.ok(Math.abs(lon - 14.4324382) < 1e-5, `lon ${lon}`);
});

test('EPSG:5513 uses the southing-westing axis order', () => {
  const [lon, lat] = TV.projection.getProjector('epsg:5513').fn(1043000, 742000);
  assert.ok(Math.abs(lat - 50.0885718) < 1e-5);
  assert.ok(Math.abs(lon - 14.4324382) < 1e-5);
});

test('Krovak round trips', () => {
  const [lon, lat] = TV.projection.krovakToWgs84(1050538.63, 568991.00);
  const [south, west] = TV.projection.wgs84ToKrovak(lon, lat);
  assert.ok(Math.abs(south - 1050538.63) < 0.01);
  assert.ok(Math.abs(west - 568991.00) < 0.01);
});

test('web mercator round trips', () => {
  const m = TV.projection.wgs84ToWebMercator(14.42, 50.08);
  const [lon, lat] = TV.projection.webMercatorToWgs84(m[0], m[1]);
  assert.ok(Math.abs(lon - 14.42) < 1e-9 && Math.abs(lat - 50.08) < 1e-9);
});

test('the coordinate system is detected from sample points', () => {
  const d = TV.projection.detectCrs;
  assert.strictEqual(d([[-742000, -1043000], [-743000, -1044000]]), 'epsg:5514');
  assert.strictEqual(d([[1043000, 742000], [1044000, 743000]]), 'epsg:5513');
  assert.strictEqual(d([[14.42, 50.08], [14.5, 50.1]]), 'wgs84');
  assert.strictEqual(d([[1000, 2000]]), 'local');
  assert.strictEqual(d([]), 'local');
});

test('an unknown system falls back to a plain cartesian view', () => {
  assert.strictEqual(TV.projection.getProjector('epsg:32633').mode, 'local');
});

/* ---------------- parser ---------------- */

const SAMPLE_ATT = [
  '$VISION',
  '* comment',
  '*',
  '$NODE:NO;XCOORD;YCOORD',
  '10;-743800.000;-1043600.000',
  '11;-743550.000;-1043600.000',
  '*',
  '$LINK:NO;FROMNODENO;TONODENO;NAME;LENGTH;WKTPOLY',
  '1;10;11;"Husova, horní";0,532km;LINESTRING(-743800 -1043600, -743550 -1043600)',
  '1;11;10;Husova;0.532km;LINESTRING(-743800 -1043600, -743550 -1043600)'
].join('\n');

test('attribute files split into tables', () => {
  const tables = TV.parser.parseAtt(SAMPLE_ATT);
  assert.deepStrictEqual(tables.map((t) => t.name), ['NODE', 'LINK']);
  assert.strictEqual(tables[1].rows.length, 2);
});

test('a quoted field keeps its separator', () => {
  const link = TV.parser.findTable(TV.parser.parseAtt(SAMPLE_ATT), ['LINK']);
  assert.strictEqual(link.rows[0].NAME, 'Husova, horní');
});

test('tab separated headers are recognised', () => {
  const tables = TV.parser.parseAtt('$LINK:NO\tFROMNODENO\tTONODENO\n1\t2\t3\n');
  assert.strictEqual(tables[0].separator, '\t');
  assert.strictEqual(tables[0].rows[0].TONODENO, '3');
});

test('Visum numbers parse whatever the locale did to them', () => {
  const n = TV.parser.parseNumber;
  assert.strictEqual(n('0,532km'), 0.532);
  assert.strictEqual(n('50km/h'), 50);
  assert.strictEqual(n('1.234,5'), 1234.5);
  assert.strictEqual(n('1,234.5'), 1234.5);
  assert.strictEqual(n('-12,7'), -12.7);
  assert.strictEqual(n('3e3'), 3000);
  assert.strictEqual(n('abc'), null);
  assert.strictEqual(n(''), null);
  assert.strictEqual(n(null), null);
});

test('WKT geometries parse, including MULTI and Z', () => {
  assert.deepStrictEqual(TV.parser.parseWkt('LINESTRING(1 2, 3 4)'), [[1, 2], [3, 4]]);
  assert.deepStrictEqual(
    TV.parser.parseWkt('MULTILINESTRING((0 0, 1 1),(1 1, 2 2))'), [[0, 0], [1, 1], [2, 2]]
  );
  assert.deepStrictEqual(TV.parser.parseWkt('LINESTRING Z (0 0 5, 1 1 6)'), [[0, 0], [1, 1]]);
  assert.deepStrictEqual(TV.parser.parseWkt('nonsense'), []);
});

test('geometry comes from WKTPOLY when it is there', () => {
  const result = TV.parser.importAtt(SAMPLE_ATT);
  assert.strictEqual(result.geometrySource, 'WKTPOLY');
  assert.strictEqual(result.links.length, 2);
});

test('geometry falls back to the node table', () => {
  const result = TV.parser.importAtt(
    '$NODE:NO;XCOORD;YCOORD\n10;0;0\n11;100;50\n$LINK:NO;FROMNODENO;TONODENO\n1;10;11\n'
  );
  assert.strictEqual(result.geometrySource, '$NODE');
  assert.deepStrictEqual(result.links[0].geom, [[0, 0], [100, 50]]);
});

test('$LINKPOLY supplies the intermediate vertices in index order', () => {
  const result = TV.parser.importAtt([
    '$NODE:NO;XCOORD;YCOORD', '10;0;0', '11;100;0',
    '$LINK:NO;FROMNODENO;TONODENO', '1;10;11',
    '$LINKPOLY:LINKNO;FROMNODENO;TONODENO;INDEX;XCOORD;YCOORD',
    '1;10;11;2;70;20', '1;10;11;1;30;20'
  ].join('\n'));
  assert.strictEqual(result.geometrySource, '$LINKPOLY');
  assert.deepStrictEqual(result.links[0].geom, [[0, 0], [30, 20], [70, 20], [100, 0]]);
});

test('relation columns such as FROMNODE\\XCOORD are understood', () => {
  const result = TV.parser.importAtt(
    '$LINK:NO;FROMNODENO;TONODENO;FROMNODE\\XCOORD;FROMNODE\\YCOORD;TONODE\\XCOORD;TONODE\\YCOORD\n'
    + '1;10;11;0;0;10;10\n'
  );
  assert.deepStrictEqual(result.links[0].geom, [[0, 0], [10, 10]]);
});

test('a missing key column is reported in plain words', () => {
  assert.throws(
    () => TV.parser.importAtt('$LINK:NAME;WKTPOLY\nHusova;LINESTRING(0 0, 1 1)\n'),
    /FROMNODENO/
  );
});

test('rows without geometry are counted as skipped', () => {
  const result = TV.parser.importAtt(
    '$LINK:NO;FROMNODENO;TONODENO;WKTPOLY\n1;10;11;LINESTRING(0 0, 1 1)\n2;11;12;\n'
  );
  assert.strictEqual(result.links.length, 1);
  assert.match(result.warnings.join(' '), /přeskočeno/);
});

test('CSV exports import too', () => {
  const result = TV.parser.importCsv(
    'NO;FROMNODENO;TONODENO;NAME;WKTPOLY\n1;10;11;Husova;LINESTRING(0 0, 1 1)\n'
  );
  assert.strictEqual(result.links[0].linkNo, '1');
});

test('GeoJSON feature collections import', () => {
  const result = TV.parser.importGeoJson(JSON.stringify({
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [[14.4, 50.1], [14.5, 50.2]] },
      properties: { NO: '1', FROMNODENO: '10', TONODENO: '11' }
    }]
  }));
  assert.deepStrictEqual(result.links[0].geom, [[14.4, 50.1], [14.5, 50.2]]);
  assert.ok(!('__GEOM__' in result.links[0].attrs));
});

test('the reverse direction is flipped so the offset lands on the right side', () => {
  const links = [
    { linkNo: '1', fromNode: '10', toNode: '11', key: '1|10|11', geom: [[0, 0], [1, 1], [2, 0]] },
    { linkNo: '1', fromNode: '11', toNode: '10', key: '1|11|10', geom: [[0, 0], [1, 1], [2, 0]] }
  ];
  TV.parser.orientDirections(links);
  assert.deepStrictEqual(links[1].geom, [[2, 0], [1, 1], [0, 0]]);
});

test('already oriented geometry is left alone', () => {
  const links = [
    { linkNo: '1', fromNode: '10', toNode: '11', key: '1|10|11', geom: [[0, 0], [2, 0]] },
    { linkNo: '1', fromNode: '11', toNode: '10', key: '1|11|10', geom: [[2, 0], [0, 0]] }
  ];
  TV.parser.orientDirections(links);
  assert.deepStrictEqual(links[1].geom, [[2, 0], [0, 0]]);
});

test('values are read back from a CSV, ignoring the bookkeeping columns', () => {
  const records = TV.parser.readValueRecords('x.csv', [
    'NO;FROMNODENO;TONODENO;NAME;VOL_MANUAL;NOTE;SURVEYOR;UPDATED_AT',
    '1;10;11;Husova;1500;pozn;Novák;2026-01-01'
  ].join('\n'));
  assert.deepStrictEqual(records, [{ key: '1|10|11', values: { VOL_MANUAL: '1500' } }]);
});

test('values are read back from an .att', () => {
  const records = TV.parser.readValueRecords(
    'x.att', '$LINK:NO;FROMNODENO;TONODENO;VOL_MANUAL\n1;10;11;1500\n1;11;10;\n'
  );
  assert.deepStrictEqual(records, [{ key: '1|10|11', values: { VOL_MANUAL: '1500' } }]);
});

/* ---------------- project ---------------- */

function makeProject(fields) {
  return new TV.Project({
    name: 'Test',
    crs: 'EPSG:4326',
    coordMode: 'geographic',
    fields: fields || [
      { name: 'VOL_MANUAL', label: 'Intenzita', valueType: 'int', unit: 'voz/den' }
    ],
    links: [
      { linkNo: '1', fromNode: '10', toNode: '11', key: '1|10|11',
        geom: [[14.4, 50.1], [14.5, 50.2]], name: 'Husova', attrs: {} },
      { linkNo: '1', fromNode: '11', toNode: '10', key: '1|11|10',
        geom: [[14.5, 50.2], [14.4, 50.1]], name: 'Husova', attrs: {} },
      { linkNo: '2', fromNode: '11', toNode: '12', key: '2|11|12',
        geom: [[14.5, 50.2], [14.5, 50.3]], name: 'Sokolská', attrs: {} }
    ]
  });
}

test('an invalid Visum attribute name is refused', () => {
  assert.throws(() => makeProject([{ name: '2 bad name' }]), /není platný název/);
});

test('a Czech decimal comma is accepted for a float field', () => {
  const project = makeProject([{ name: 'SPEED', label: 'Rychlost', valueType: 'float' }]);
  project.setValues('1|10|11', { SPEED: '48,5' });
  assert.strictEqual(project.valuesOf('1|10|11').SPEED, '48.5');
});

test('spaces used as thousands separators are accepted', () => {
  const project = makeProject();
  project.setValues('1|10|11', { VOL_MANUAL: '12 500' });
  assert.strictEqual(project.valuesOf('1|10|11').VOL_MANUAL, '12500');
});

test('a fractional value is refused for an integer field', () => {
  const project = makeProject();
  assert.throws(() => project.setValues('1|10|11', { VOL_MANUAL: '12.5' }), /celé číslo/);
});

test('text that is not a number is refused', () => {
  const project = makeProject();
  assert.throws(() => project.setValues('1|10|11', { VOL_MANUAL: 'abc' }), /není číslo/);
});

test('an unknown value name is refused', () => {
  const project = makeProject();
  assert.throws(() => project.setValues('1|10|11', { NOPE: '1' }), /Neznámá veličina/);
});

test('an unknown direction is refused', () => {
  const project = makeProject();
  assert.throws(() => project.setValues('9|1|2', { VOL_MANUAL: '1' }), /není součástí/);
});

test('the two directions of a link hold their own values', () => {
  const project = makeProject();
  project.setValues('1|10|11', { VOL_MANUAL: '1500' });
  project.setValues('1|11|10', { VOL_MANUAL: '900' });
  assert.strictEqual(project.valuesOf('1|10|11').VOL_MANUAL, '1500');
  assert.strictEqual(project.valuesOf('1|11|10').VOL_MANUAL, '900');
});

test('the opposite direction is found, and only when it exists', () => {
  const project = makeProject();
  assert.strictEqual(project.reverseKey('1|10|11'), '1|11|10');
  assert.strictEqual(project.reverseKey('2|11|12'), null);
});

test('an empty value clears the entry', () => {
  const project = makeProject();
  project.setValues('1|10|11', { VOL_MANUAL: '1500' });
  project.setValues('1|10|11', { VOL_MANUAL: '' });
  assert.strictEqual(project.stats().filled, 0);
  assert.strictEqual(project.entry('1|10|11').status, 'empty');
});

test('a note survives clearing the numbers', () => {
  const project = makeProject();
  project.setValues('1|10|11', { VOL_MANUAL: '' }, { note: 'nelze změřit' });
  assert.strictEqual(project.entry('1|10|11').note, 'nelze změřit');
});

test('every change lands in the history, unchanged values do not', () => {
  const project = makeProject();
  project.setValues('1|10|11', { VOL_MANUAL: '1500' }, { surveyor: 'A' });
  project.setValues('1|10|11', { VOL_MANUAL: '1600' }, { surveyor: 'B' });
  project.setValues('1|10|11', { VOL_MANUAL: '1600' }, { surveyor: 'B' });
  assert.strictEqual(project.history.length, 2);
  assert.deepStrictEqual(
    [project.history[1].from, project.history[1].to, project.history[1].surveyor],
    ['1500', '1600', 'B']
  );
});

test('stats count filled and flagged directions', () => {
  const project = makeProject();
  project.setValues('1|10|11', { VOL_MANUAL: '1500' });
  project.setValues('2|11|12', { VOL_MANUAL: '10' }, { status: 'flagged' });
  assert.deepStrictEqual(project.stats(), { total: 3, filled: 2, flagged: 1, remaining: 1 });
});

test('clearing removes the values and the note', () => {
  const project = makeProject();
  project.setValues('1|10|11', { VOL_MANUAL: '1500' }, { note: 'x' });
  project.clearValues('1|10|11');
  assert.deepStrictEqual(project.valuesOf('1|10|11'), {});
  assert.strictEqual(project.entry('1|10|11').note, '');
});

test('imported records land on the matching directions and report the rest', () => {
  const project = makeProject();
  const result = project.importRecords([
    { key: '1|10|11', values: { VOL_MANUAL: '1500' } },
    { key: '9|1|2', values: { VOL_MANUAL: '5' } },
    { key: '2|11|12', values: { UNKNOWN_FIELD: '7' } }
  ]);
  assert.deepStrictEqual(result, { updated: 1, missing: 1 });
  assert.strictEqual(project.valuesOf('1|10|11').VOL_MANUAL, '1500');
});

test('keepExisting leaves values already typed in alone', () => {
  const project = makeProject();
  project.setValues('1|10|11', { VOL_MANUAL: '1500' });
  project.importRecords([{ key: '1|10|11', values: { VOL_MANUAL: '9999' } }],
    { keepExisting: true });
  assert.strictEqual(project.valuesOf('1|10|11').VOL_MANUAL, '1500');
});

test('a project survives a JSON round trip', () => {
  const project = makeProject();
  project.setValues('1|10|11', { VOL_MANUAL: '1500' }, { note: 'ok', surveyor: 'Novák' });
  const restored = TV.Project.fromJSON(JSON.parse(JSON.stringify(project.toJSON())));
  assert.strictEqual(restored.links.length, 3);
  assert.strictEqual(restored.valuesOf('1|10|11').VOL_MANUAL, '1500');
  assert.strictEqual(restored.entry('1|10|11').note, 'ok');
  assert.strictEqual(restored.reverseKey('1|10|11'), '1|11|10');
});

test('a foreign JSON file is rejected', () => {
  assert.throws(() => TV.Project.fromJSON({ hello: 'world' }), /uloženou práci/);
});

test('fromImport projects the coordinates and drops duplicates', () => {
  const imported = TV.parser.importAtt(SAMPLE_ATT);
  imported.links.push(Object.assign({}, imported.links[0]));
  const project = TV.Project.fromImport(imported, { name: 'X', crs: 'epsg:5514' });
  assert.strictEqual(project.links.length, 2);
  assert.strictEqual(project.coordMode, 'geographic');
  const [lon, lat] = project.links[0].geom[0];
  assert.ok(lon > 14.3 && lon < 14.5 && lat > 50.0 && lat < 50.2, `${lon} ${lat}`);
});

/* ---------------- exporters ---------------- */

function filledProject() {
  const project = makeProject();
  project.name = 'Sčítání 2026';
  project.setValues('1|10|11', { VOL_MANUAL: '12500' }, { note: 'ruční sčítání', surveyor: 'Novák' });
  project.setValues('1|11|10', { VOL_MANUAL: '9800' });
  return project;
}

test('the CSV carries the Visum key columns and the notes', () => {
  const csv = TV.exporters.toCsv(filledProject());
  const lines = csv.trim().split('\r\n');
  assert.strictEqual(lines[0],
    'NO;FROMNODENO;TONODENO;NAME;VOL_MANUAL;NOTE;SURVEYOR;UPDATED_AT');
  assert.strictEqual(lines.length, 3);
  assert.match(csv, /ruční sčítání/);
});

test('a semicolon inside a name is quoted in the CSV', () => {
  const project = filledProject();
  project.byKey['1|10|11'].name = 'Husova; horní';
  assert.match(TV.exporters.toCsv(project), /"Husova; horní"/);
});

test('the .att keys one direction per row and stays ASCII', () => {
  const att = TV.exporters.toAtt(filledProject());
  assert.ok(att.startsWith('$VISION'));
  assert.match(att, /\$LINK:NO;FROMNODENO;TONODENO;VOL_MANUAL/);
  assert.match(att, /^1;10;11;12500$/m);
  assert.match(att, /^1;11;10;9800$/m);
  assert.match(att, /Scitani 2026/);            // diacritics transliterated
  // eslint-disable-next-line no-control-regex
  assert.ok(!/[^\x00-\x7F]/.test(att), 'the attribute file must be pure ASCII');
});

test('the .att names the user attribute and its Visum type', () => {
  const att = TV.exporters.toAtt(filledProject());
  assert.match(att, /VOL_MANUAL\s+Integer/);
});

test('empty directions are left out unless asked for', () => {
  const project = filledProject();
  assert.strictEqual(TV.exporters.rowsOf(project, false).length, 2);
  assert.strictEqual(TV.exporters.rowsOf(project, true).length, 3);
  assert.match(TV.exporters.toAtt(project, { includeEmpty: true }), /^2;11;12;$/m);
});

test('rows come out in Visum link number order', () => {
  const project = makeProject();
  project.links.push({ linkNo: '10', fromNode: '1', toNode: '2', key: '10|1|2',
    geom: [[14.4, 50.1], [14.5, 50.1]], name: '', attrs: {} });
  project.byKey['10|1|2'] = project.links[project.links.length - 1];
  const order = TV.exporters.rowsOf(project, true).map((l) => l.linkNo);
  assert.deepStrictEqual(order, ['1', '1', '2', '10']);
});

test('float values are written with a dot, whatever was typed', () => {
  const project = makeProject([{ name: 'SPEED', label: 'Rychlost', valueType: 'float' }]);
  project.setValues('1|10|11', { SPEED: '48,5' });
  assert.match(TV.exporters.toAtt(project), /^1;10;11;48\.5$/m);
});

test('GeoJSON carries the values and refuses local coordinates', () => {
  const data = JSON.parse(TV.exporters.toGeoJson(filledProject()));
  assert.strictEqual(data.features.length, 3);
  assert.strictEqual(data.features[0].properties.VOL_MANUAL, '12500');
  const local = makeProject();
  local.coordMode = 'local';
  assert.throws(() => TV.exporters.toGeoJson(local), /zeměpisné souřadnice/);
});

test('the generated Visum script is valid Python-looking output naming the attribute', () => {
  const script = TV.exporters.visumScript(filledProject(), 'out.att');
  assert.match(script, /AddUserDefinedAttribute/);
  assert.match(script, /LoadAttributeFile/);
  assert.match(script, /"VOL_MANUAL", "Intenzita", 1/);
});

test('file names are transliterated into something every system accepts', () => {
  assert.strictEqual(TV.exporters.slug('Sčítání 2026'), 'Scitani_2026');
  assert.strictEqual(TV.exporters.slug('***'), 'export');
});
