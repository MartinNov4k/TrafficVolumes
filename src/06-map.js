/* Canvas map of link directions.
 *
 * Dependency free on purpose: this has to run from a file:// URL on a locked
 * down machine. Each direction is drawn as its own polyline, offset to the
 * right hand side of the travel direction, which is how volume plots are read.
 */
(function (TV) {
  'use strict';

  var TILE_SIZE = 256;
  var COLOR_EMPTY = '#8b96a8';
  var COLOR_FLAGGED = '#f5a524';
  var COLOR_SELECTED = '#ffffff';
  var RAMP = ['#3fb27f', '#8fd14f', '#f2c14e', '#ef8a3c', '#e0503f'];

  function TrafficMap(canvas, options) {
    var opts = options || {};
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.geographic = opts.geographic !== false;
    this.project = null;
    this.items = [];
    this.byKey = {};
    this.visible = [];
    this.selectedKey = null;
    this.hoverKey = null;
    this.showLabels = true;
    this.showBands = true;
    this.showArrows = true;
    this.basemapUrl = '';
    this.basemapEnabled = false;
    this.valueField = null;
    this.maxValue = 1;
    this.filterKeys = null;   // when set, only these directions are drawn
    this.background = '#0c111b';
    this.onSelect = opts.onSelect || function () {};
    this.onHover = opts.onHover || function () {};

    this.centre = [0, 0];
    this.scale = 1;
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this._tiles = {};
    this._tileOrder = [];
    this._frame = null;
    this._pointers = {};
    this._pointerCount = 0;
    this._pinchDistance = 0;
    this._moved = false;

    this._bindEvents();
    this.resize();
    var self = this;
    window.addEventListener('resize', function () { self.resize(); self.draw(); });
  }

  TrafficMap.prototype.lonLatToWorld = function (lon, lat) {
    return TV.projection.wgs84ToWebMercator(lon, lat);
  };

  /* -- data ---------------------------------------------------------------- */

  TrafficMap.prototype.setProject = function (project) {
    this.project = project;
    this.geographic = project.coordMode === 'geographic';
    this.valueField = project.primaryField();
    var self = this;
    this.items = project.links.map(function (link) { return self._prepare(link); });
    this.byKey = {};
    this.items.forEach(function (item) { self.byKey[item.key] = item; });
    this._recomputeMax();
    return this.items.length;
  };

  TrafficMap.prototype._prepare = function (link) {
    var count = link.geom.length;
    var world = new Float64Array(count * 2);
    var minx = Infinity;
    var miny = Infinity;
    var maxx = -Infinity;
    var maxy = -Infinity;
    for (var i = 0; i < count; i += 1) {
      var x = link.geom[i][0];
      var y = link.geom[i][1];
      if (this.geographic) {
        var p = this.lonLatToWorld(x, y);
        x = p[0];
        y = p[1];
      }
      world[i * 2] = x;
      world[i * 2 + 1] = y;
      if (x < minx) minx = x;
      if (y < miny) miny = y;
      if (x > maxx) maxx = x;
      if (y > maxy) maxy = y;
    }
    return {
      key: link.key,
      link: link,
      world: world,
      bbox: [minx, miny, maxx, maxy],
      value: this.project ? this.project.numericValue(link.key, this.valueField) : null,
      status: this.project ? this.project.entry(link.key).status : 'empty',
      screen: null,
      width: 3
    };
  };

  /** Pick up a value that changed without rebuilding the whole network. */
  TrafficMap.prototype.refresh = function (key) {
    var item = this.byKey[key];
    if (!item || !this.project) return;
    item.value = this.project.numericValue(key, this.valueField);
    item.status = this.project.entry(key).status;
    this._recomputeMax();
    this.draw();
  };

  TrafficMap.prototype.setValueField = function (name) {
    this.valueField = name;
    var self = this;
    this.items.forEach(function (item) {
      item.value = self.project.numericValue(item.key, name);
    });
    this._recomputeMax();
    this.draw();
  };

  TrafficMap.prototype._recomputeMax = function () {
    var max = 1;
    for (var i = 0; i < this.items.length; i += 1) {
      var value = this.items[i].value;
      if (value !== null && value > max) max = value;
    }
    this.maxValue = max;
  };

  /* -- view ---------------------------------------------------------------- */

  TrafficMap.prototype.resize = function () {
    var rect = this.canvas.getBoundingClientRect();
    this.width = Math.max(1, Math.round(rect.width));
    this.height = Math.max(1, Math.round(rect.height));
    this.canvas.width = Math.round(this.width * this.dpr);
    this.canvas.height = Math.round(this.height * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  };

  TrafficMap.prototype.fitBounds = function (bounds, padding) {
    if (!bounds) return;
    var minx = bounds[0];
    var miny = bounds[1];
    var maxx = bounds[2];
    var maxy = bounds[3];
    if (this.geographic) {
      var a = this.lonLatToWorld(minx, miny);
      var b = this.lonLatToWorld(maxx, maxy);
      minx = Math.min(a[0], b[0]);
      miny = Math.min(a[1], b[1]);
      maxx = Math.max(a[0], b[0]);
      maxy = Math.max(a[1], b[1]);
    }
    var pad = padding === undefined ? 48 : padding;
    this.centre = [(minx + maxx) / 2, (miny + maxy) / 2];
    this.scale = Math.min(
      (this.width - 2 * pad) / Math.max(maxx - minx, 1e-6),
      (this.height - 2 * pad) / Math.max(maxy - miny, 1e-6)
    );
    if (!isFinite(this.scale) || this.scale <= 0) this.scale = 1;
    this.draw();
  };

  TrafficMap.prototype.toScreen = function (wx, wy) {
    return [
      (wx - this.centre[0]) * this.scale + this.width / 2,
      this.height / 2 - (wy - this.centre[1]) * this.scale
    ];
  };

  TrafficMap.prototype.toWorld = function (sx, sy) {
    return [
      (sx - this.width / 2) / this.scale + this.centre[0],
      this.centre[1] - (sy - this.height / 2) / this.scale
    ];
  };

  TrafficMap.prototype.zoomBy = function (factor, anchorX, anchorY) {
    var ax = anchorX === undefined ? this.width / 2 : anchorX;
    var ay = anchorY === undefined ? this.height / 2 : anchorY;
    var before = this.toWorld(ax, ay);
    this.scale = Math.max(1e-9, Math.min(this.scale * factor, 1e6));
    var after = this.toWorld(ax, ay);
    this.centre = [
      this.centre[0] + (before[0] - after[0]),
      this.centre[1] + (before[1] - after[1])
    ];
    this.draw();
  };

  TrafficMap.prototype.centreOnKey = function (key) {
    var item = this.byKey[key];
    if (!item) return;
    var index = Math.floor((item.world.length / 2) / 2);
    this.centre = [item.world[index * 2], item.world[index * 2 + 1]];
    this.draw();
  };

  /** Restrict drawing and hit testing to a set of keys, or pass null to clear. */
  TrafficMap.prototype.setFilter = function (keys) {
    this.filterKeys = keys;
    this.draw();
  };

  TrafficMap.prototype.setBasemap = function (url, enabled) {
    this.basemapUrl = url || '';
    this.basemapEnabled = !!enabled && !!url && this.geographic;
    this.draw();
  };

  /* -- drawing ------------------------------------------------------------- */

  TrafficMap.prototype.draw = function () {
    if (this._frame) return;
    var self = this;
    this._frame = requestAnimationFrame(function () {
      self._frame = null;
      self._render();
    });
  };

  TrafficMap.prototype._render = function () {
    var ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.fillStyle = this.background;
    ctx.fillRect(0, 0, this.width, this.height);
    if (this.basemapEnabled) this._drawTiles();
    this._drawLinks();
  };

  TrafficMap.prototype._drawTiles = function () {
    var mercHalf = TV.projection.MERC_HALF;
    var z = Math.round(Math.log(2 * mercHalf * this.scale / TILE_SIZE) / Math.LN2);
    z = Math.max(0, Math.min(19, z));
    var n = Math.pow(2, z);
    var tileWorld = (2 * mercHalf) / n;
    var topLeft = this.toWorld(0, 0);
    var bottomRight = this.toWorld(this.width, this.height);
    var x0 = Math.floor((topLeft[0] + mercHalf) / tileWorld);
    var x1 = Math.ceil((bottomRight[0] + mercHalf) / tileWorld);
    var y0 = Math.floor((mercHalf - topLeft[1]) / tileWorld);
    var y1 = Math.ceil((mercHalf - bottomRight[1]) / tileWorld);
    var size = tileWorld * this.scale;

    for (var ty = y0; ty < y1; ty += 1) {
      if (ty < 0 || ty >= n) continue;
      for (var tx = x0; tx < x1; tx += 1) {
        var wrapped = ((tx % n) + n) % n;
        var image = this._tile(z, wrapped, ty);
        if (!image || !image.complete || !image.naturalWidth) continue;
        var at = this.toScreen(tx * tileWorld - mercHalf, mercHalf - ty * tileWorld);
        this.ctx.drawImage(image, at[0], at[1], size + 1, size + 1);
      }
    }
  };

  TrafficMap.prototype._tile = function (z, x, y) {
    var id = z + '/' + x + '/' + y;
    if (this._tiles[id]) return this._tiles[id];
    if (this._tileOrder.length > 400) {
      var drop = this._tileOrder.splice(0, 100);
      var self0 = this;
      drop.forEach(function (key) { delete self0._tiles[key]; });
    }
    var image = new Image();
    image.crossOrigin = 'anonymous';
    var self = this;
    image.onload = function () { self.draw(); };
    image.onerror = function () { image.failed = true; };
    image.src = this.basemapUrl
      .replace('{z}', z).replace('{x}', x).replace('{y}', y)
      .replace('{s}', 'abc'[(x + y) % 3]);
    this._tiles[id] = image;
    this._tileOrder.push(id);
    return image;
  };

  TrafficMap.prototype._widthOf = function (item) {
    if (!this.showBands || item.value === null) return 3;
    return 2.5 + 15 * Math.sqrt(Math.max(0, item.value) / this.maxValue);
  };

  TrafficMap.prototype._colourOf = function (item) {
    if (item.status === 'flagged') return COLOR_FLAGGED;
    if (item.value === null) return COLOR_EMPTY;
    var ratio = Math.max(0, Math.min(1, item.value / this.maxValue));
    return RAMP[Math.min(RAMP.length - 1, Math.floor(ratio * RAMP.length))];
  };

  /** Project a link and offset it to the right of the travel direction. */
  TrafficMap.prototype._screenPath = function (item, offset) {
    var world = item.world;
    var count = world.length / 2;
    var points = new Array(count);
    for (var i = 0; i < count; i += 1) {
      points[i] = this.toScreen(world[i * 2], world[i * 2 + 1]);
    }
    if (!offset) return points;
    var out = new Array(count);
    for (var j = 0; j < count; j += 1) {
      var nx = 0;
      var ny = 0;
      // Average the right hand normals of the adjacent segments.
      for (var s = 0; s < 2; s += 1) {
        var a = s === 0 ? j - 1 : j;
        var b = s === 0 ? j : j + 1;
        if (a < 0 || b >= count) continue;
        var dx = points[b][0] - points[a][0];
        var dy = points[b][1] - points[a][1];
        var len = Math.sqrt(dx * dx + dy * dy);
        if (len < 1e-9) continue;
        // Screen y points down, so rotating the direction by +90 degrees,
        // (x, y) -> (-y, x), gives the right hand side of travel.
        nx += -dy / len;
        ny += dx / len;
      }
      var norm = Math.sqrt(nx * nx + ny * ny);
      out[j] = norm < 1e-9
        ? points[j]
        : [points[j][0] + (nx / norm) * offset, points[j][1] + (ny / norm) * offset];
    }
    return out;
  };

  TrafficMap.prototype._drawLinks = function () {
    var ctx = this.ctx;
    var a = this.toWorld(0, this.height);
    var b = this.toWorld(this.width, 0);
    var margin = 200 / this.scale;
    var vminx = a[0] - margin;
    var vminy = a[1] - margin;
    var vmaxx = b[0] + margin;
    var vmaxy = b[1] + margin;

    var visible = [];
    for (var i = 0; i < this.items.length; i += 1) {
      var item = this.items[i];
      if (this.filterKeys && !this.filterKeys[item.key]) {
        item.screen = null;
        continue;
      }
      var box = item.bbox;
      if (box[2] < vminx || box[0] > vmaxx || box[3] < vminy || box[1] > vmaxy) {
        item.screen = null;
        continue;
      }
      item.width = this._widthOf(item);
      item.screen = this._screenPath(item, item.width / 2 + 1.5);
      visible.push(item);
    }
    this.visible = visible;

    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    // Two passes so filled directions stay readable over the grey ones.
    for (var pass = 0; pass < 2; pass += 1) {
      for (var v = 0; v < visible.length; v += 1) {
        var current = visible[v];
        var filled = current.value !== null || current.status === 'flagged';
        if ((pass === 0) === filled) continue;
        this._strokePath(current.screen, this._colourOf(current), current.width);
      }
    }

    if (this.showArrows) {
      for (var w = 0; w < visible.length; w += 1) this._drawArrow(visible[w]);
    }

    // Highlights go on before the labels so a selected direction never paints
    // over its own value.
    var keys = [this.hoverKey, this.selectedKey];
    for (var k = 0; k < keys.length; k += 1) {
      var picked = keys[k] && this.byKey[keys[k]];
      if (!picked || !picked.screen) continue;
      this._strokePath(picked.screen, COLOR_SELECTED, picked.width + 4, 0.9);
      this._strokePath(picked.screen, this._colourOf(picked), picked.width);
      this._drawArrow(picked);
    }
    if (this.showLabels) this._drawLabels(visible);
  };

  TrafficMap.prototype._strokePath = function (points, colour, width, alpha) {
    if (!points || points.length < 2) return;
    var ctx = this.ctx;
    ctx.globalAlpha = alpha === undefined ? 1 : alpha;
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    for (var i = 1; i < points.length; i += 1) ctx.lineTo(points[i][0], points[i][1]);
    ctx.stroke();
    ctx.globalAlpha = 1;
  };

  TrafficMap.prototype._drawArrow = function (item) {
    var points = item.screen;
    if (!points || points.length < 2) return;
    var end = points[points.length - 1];
    var previous = points[points.length - 2];
    var dx = end[0] - previous[0];
    var dy = end[1] - previous[1];
    var len = Math.sqrt(dx * dx + dy * dy);
    if (len < 12) return;
    var ux = dx / len;
    var uy = dy / len;
    // Sit the head a little before the node so arrows do not pile up there.
    var tipX = end[0] - ux * 6;
    var tipY = end[1] - uy * 6;
    var size = Math.max(5, Math.min(9, item.width + 3));
    var ctx = this.ctx;
    ctx.fillStyle = this._colourOf(item);
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(tipX - ux * size - uy * size * 0.5, tipY - uy * size + ux * size * 0.5);
    ctx.lineTo(tipX - ux * size + uy * size * 0.5, tipY - uy * size - ux * size * 0.5);
    ctx.closePath();
    ctx.fill();
  };

  function overlaps(a, b) {
    return !(a[2] < b[0] || a[0] > b[2] || a[3] < b[1] || a[1] > b[3]);
  }

  TrafficMap.prototype._drawLabels = function (visible) {
    var ctx = this.ctx;
    ctx.font = '600 11px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineWidth = 3;
    ctx.strokeStyle = 'rgba(8,12,20,.85)';

    // Labels of the two directions of one link would otherwise land on top of
    // each other, so each is pushed out to its own side and anything that still
    // collides is dropped rather than drawn illegibly.
    var placed = [];
    var drawn = 0;
    for (var i = 0; i < visible.length && drawn < 600; i += 1) {
      var item = visible[i];
      if (item.value === null) continue;
      var points = item.screen;
      if (!points || points.length < 2) continue;
      var start = points[0];
      var end = points[points.length - 1];
      if (Math.sqrt(Math.pow(end[0] - start[0], 2) + Math.pow(end[1] - start[1], 2)) < 34) {
        continue;
      }
      var index = Math.max(1, Math.floor(points.length / 2));
      var a = points[index - 1];
      var b = points[index];
      var dx = b[0] - a[0];
      var dy = b[1] - a[1];
      var len = Math.sqrt(dx * dx + dy * dy) || 1;
      var push = item.width / 2 + 8;
      var cx = (a[0] + b[0]) / 2 + (-dy / len) * push;
      var cy = (a[1] + b[1]) / 2 + (dx / len) * push;

      var text = item.value.toLocaleString('cs-CZ');
      var half = ctx.measureText(text).width / 2 + 2;
      var box = [cx - half, cy - 7, cx + half, cy + 7];
      var collides = false;
      for (var p = 0; p < placed.length; p += 1) {
        if (overlaps(box, placed[p])) { collides = true; break; }
      }
      if (collides) continue;
      placed.push(box);
      ctx.strokeText(text, cx, cy);
      ctx.fillStyle = '#eef3fa';
      ctx.fillText(text, cx, cy);
      drawn += 1;
    }
  };

  /* -- PNG export ---------------------------------------------------------- */

  /**
   * Render the current view into a standalone canvas with a title strip and a
   * legend, for pasting into a report.
   */
  TrafficMap.prototype.exportImage = function (options) {
    var settings = options || {};
    var scale = settings.scale || 2;
    var headerHeight = 54;
    var footerHeight = 34;
    var out = document.createElement('canvas');
    out.width = Math.round(this.width * scale);
    out.height = Math.round((this.height + headerHeight + footerHeight) * scale);
    var ctx = out.getContext('2d');
    ctx.setTransform(scale, 0, 0, scale, 0, 0);

    ctx.fillStyle = this.background;
    ctx.fillRect(0, 0, this.width, this.height + headerHeight + footerHeight);

    // Reuse the live renderer by pointing it at the export canvas.
    var savedCtx = this.ctx;
    var savedDpr = this.dpr;
    this.ctx = ctx;
    ctx.save();
    ctx.translate(0, headerHeight);
    ctx.beginPath();
    ctx.rect(0, 0, this.width, this.height);
    ctx.clip();
    this._render();
    ctx.restore();
    this.ctx = savedCtx;
    this.dpr = savedDpr;

    ctx.fillStyle = '#161d2c';
    ctx.fillRect(0, 0, this.width, headerHeight);
    ctx.fillRect(0, this.height + headerHeight, this.width, footerHeight);

    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    ctx.fillStyle = '#e6ebf2';
    ctx.font = '600 17px "Segoe UI", system-ui, sans-serif';
    ctx.fillText(settings.title || '', 16, 21);
    ctx.fillStyle = '#94a3b8';
    ctx.font = '12px "Segoe UI", system-ui, sans-serif';
    ctx.fillText(settings.subtitle || '', 16, 40);

    // Legend: grey for untouched, then the low to high ramp.
    var x = 16;
    var y = this.height + headerHeight + footerHeight / 2;
    function swatch(colour, label) {
      ctx.fillStyle = colour;
      ctx.fillRect(x, y - 5, 10, 10);
      x += 14;
      if (label) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '12px "Segoe UI", system-ui, sans-serif';
        ctx.fillText(label, x, y);
        x += ctx.measureText(label).width + 14;
      }
    }
    swatch(COLOR_EMPTY, 'nevyplněno');
    RAMP.forEach(function (colour) { swatch(colour, null); });
    x += 4;
    ctx.fillStyle = '#94a3b8';
    ctx.fillText('nízká → vysoká intenzita', x, y);
    x += ctx.measureText('nízká → vysoká intenzita').width + 14;
    swatch(COLOR_FLAGGED, 'k prověření');

    ctx.textAlign = 'right';
    ctx.fillStyle = '#94a3b8';
    ctx.fillText(settings.footerRight || '', this.width - 16, y);
    return out;
  };

  /* -- interaction --------------------------------------------------------- */

  TrafficMap.prototype.pick = function (sx, sy) {
    var best = null;
    var bestDistance = 9;
    for (var i = 0; i < this.visible.length; i += 1) {
      var item = this.visible[i];
      var points = item.screen;
      if (!points) continue;
      var tolerance = Math.max(9, item.width / 2 + 3);
      for (var j = 1; j < points.length; j += 1) {
        var d = distanceToSegment(sx, sy, points[j - 1], points[j]);
        if (d < tolerance && d < bestDistance) {
          bestDistance = d;
          best = item;
        }
      }
    }
    return best;
  };

  TrafficMap.prototype.select = function (key, centre) {
    this.selectedKey = key;
    if (centre && key) this.centreOnKey(key);
    this.draw();
  };

  TrafficMap.prototype._bindEvents = function () {
    var canvas = this.canvas;
    var self = this;

    canvas.addEventListener('pointerdown', function (event) {
      canvas.setPointerCapture(event.pointerId);
      self._pointers[event.pointerId] = [event.offsetX, event.offsetY];
      self._pointerCount += 1;
      self._moved = false;
      self._dragFrom = [event.offsetX, event.offsetY];
      self._dragCentre = self.centre.slice();
      canvas.classList.add('dragging');
    });

    canvas.addEventListener('pointermove', function (event) {
      if (self._pointers[event.pointerId] === undefined) {
        var hit = self.pick(event.offsetX, event.offsetY);
        var key = hit ? hit.key : null;
        if (key !== self.hoverKey) {
          self.hoverKey = key;
          canvas.style.cursor = hit ? 'pointer' : '';
          self.onHover(hit ? hit.link : null);
          self.draw();
        }
        return;
      }
      self._pointers[event.pointerId] = [event.offsetX, event.offsetY];
      if (self._pointerCount >= 2) { self._handlePinch(); return; }
      var dx = event.offsetX - self._dragFrom[0];
      var dy = event.offsetY - self._dragFrom[1];
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) self._moved = true;
      self.centre = [
        self._dragCentre[0] - dx / self.scale,
        self._dragCentre[1] + dy / self.scale
      ];
      self.draw();
    });

    function release(event) {
      if (self._pointers[event.pointerId] === undefined) return;
      delete self._pointers[event.pointerId];
      self._pointerCount = Math.max(0, self._pointerCount - 1);
      self._pinchDistance = 0;
      canvas.classList.remove('dragging');
      if (!self._moved) {
        var hit = self.pick(event.offsetX, event.offsetY);
        self.selectedKey = hit ? hit.key : null;
        self.draw();
        self.onSelect(hit ? hit.link : null);
      }
    }
    canvas.addEventListener('pointerup', release);
    canvas.addEventListener('pointercancel', function (event) {
      delete self._pointers[event.pointerId];
      self._pointerCount = Math.max(0, self._pointerCount - 1);
      canvas.classList.remove('dragging');
    });

    canvas.addEventListener('wheel', function (event) {
      event.preventDefault();
      self.zoomBy(Math.pow(1.0015, -event.deltaY), event.offsetX, event.offsetY);
    }, { passive: false });

    canvas.addEventListener('dblclick', function (event) {
      self.zoomBy(2, event.offsetX, event.offsetY);
    });

    canvas.addEventListener('contextmenu', function (event) { event.preventDefault(); });
  };

  TrafficMap.prototype._handlePinch = function () {
    var self = this;
    var points = Object.keys(this._pointers).map(function (id) { return self._pointers[id]; });
    if (points.length < 2) return;
    var distance = Math.sqrt(
      Math.pow(points[0][0] - points[1][0], 2) + Math.pow(points[0][1] - points[1][1], 2)
    );
    var cx = (points[0][0] + points[1][0]) / 2;
    var cy = (points[0][1] + points[1][1]) / 2;
    if (this._pinchDistance > 0 && distance > 0) {
      this.zoomBy(distance / this._pinchDistance, cx, cy);
    }
    this._pinchDistance = distance;
    this._moved = true;
  };

  function distanceToSegment(px, py, a, b) {
    var dx = b[0] - a[0];
    var dy = b[1] - a[1];
    var lengthSquared = dx * dx + dy * dy;
    if (lengthSquared < 1e-12) {
      return Math.sqrt(Math.pow(px - a[0], 2) + Math.pow(py - a[1], 2));
    }
    var t = ((px - a[0]) * dx + (py - a[1]) * dy) / lengthSquared;
    t = Math.max(0, Math.min(1, t));
    return Math.sqrt(
      Math.pow(px - (a[0] + t * dx), 2) + Math.pow(py - (a[1] + t * dy), 2)
    );
  }

  TV.TrafficMap = TrafficMap;
  TV.mapColours = {
    EMPTY: COLOR_EMPTY, FLAGGED: COLOR_FLAGGED, RAMP: RAMP
  };
})(typeof globalThis !== 'undefined'
  ? (globalThis.TV = globalThis.TV || {})
  : (this.TV = this.TV || {}));
