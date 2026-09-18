/* Canvas map for link directions.
 *
 * Deliberately dependency free: the surveyor often works on a locked down
 * machine with no internet, so everything from the projection to the tile grid
 * and the hit testing lives here. Each direction of a link is drawn as its own
 * polyline, offset to the right hand side of the travel direction, which is how
 * volume plots are read in Visum.
 */
'use strict';

const EARTH_R = 6378137;
const MERC_HALF = Math.PI * EARTH_R;
const TILE_SIZE = 256;

const COLOR_EMPTY = '#8b96a8';
const COLOR_FLAGGED = '#f5a524';
const COLOR_SELECTED = '#ffffff';
const RAMP = ['#3fb27f', '#8fd14f', '#f2c14e', '#ef8a3c', '#e0503f'];

function lonLatToWorld(lon, lat) {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  return [
    (lon * Math.PI / 180) * EARTH_R,
    Math.log(Math.tan(Math.PI / 4 + (clamped * Math.PI / 180) / 2)) * EARTH_R,
  ];
}

function worldToLonLat(x, y) {
  return [
    (x / EARTH_R) * 180 / Math.PI,
    (2 * Math.atan(Math.exp(y / EARTH_R)) - Math.PI / 2) * 180 / Math.PI,
  ];
}

class TrafficMap {
  constructor(canvas, options) {
    const opts = options || {};
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.geographic = opts.geographic !== false;
    this.items = [];
    this.byKey = new Map();
    this.selectedKey = null;
    this.hoverKey = null;
    this.showLabels = true;
    this.showBands = true;
    this.basemapUrl = '';
    this.basemapEnabled = false;
    this.valueField = null;
    this.maxValue = 1;
    this.onSelect = opts.onSelect || function () {};
    this.onViewChange = opts.onViewChange || function () {};

    this.centre = [0, 0];
    this.scale = 1;              // screen pixels per world unit
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this._tiles = new Map();
    this._frame = null;
    this._pointers = new Map();
    this._pinchDistance = 0;
    this._moved = false;

    this._bindEvents();
    this._resize();
    window.addEventListener('resize', () => { this._resize(); this.draw(); });
  }

  /* -- data ---------------------------------------------------------------- */

  setData(links, valueField) {
    this.valueField = valueField || null;
    this.items = links.map((link) => this._prepare(link));
    this.byKey = new Map(this.items.map((item) => [item.key, item]));
    this._recomputeMax();
    return this.items.length;
  }

  updateLink(link) {
    const existing = this.byKey.get(link.key);
    const prepared = this._prepare(link, existing);
    if (existing) {
      const index = this.items.indexOf(existing);
      this.items[index] = prepared;
    } else {
      this.items.push(prepared);
    }
    this.byKey.set(link.key, prepared);
    this._recomputeMax();
    this.draw();
  }

  _prepare(link, previous) {
    const coords = link.geom;
    const world = new Float64Array(coords.length * 2);
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    for (let i = 0; i < coords.length; i += 1) {
      let x = coords[i][0];
      let y = coords[i][1];
      if (this.geographic) {
        const p = lonLatToWorld(x, y);
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
      data: link,
      world: world,
      bbox: [minx, miny, maxx, maxy],
      value: this._valueOf(link),
      screen: (previous && previous.screen) || null,
    };
  }

  _valueOf(link) {
    if (!this.valueField) return null;
    const raw = link.values ? link.values[this.valueField] : null;
    if (raw === undefined || raw === null || raw === '') return null;
    const number = parseFloat(String(raw).replace(',', '.'));
    return Number.isFinite(number) ? number : null;
  }

  _recomputeMax() {
    let max = 1;
    for (const item of this.items) {
      if (item.value !== null && item.value > max) max = item.value;
    }
    this.maxValue = max;
  }

  /* -- view ---------------------------------------------------------------- */

  _resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.width = Math.max(1, Math.round(rect.width));
    this.height = Math.max(1, Math.round(rect.height));
    this.canvas.width = Math.round(this.width * this.dpr);
    this.canvas.height = Math.round(this.height * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  }

  fitBounds(bounds, padding) {
    if (!bounds) return;
    let [minx, miny, maxx, maxy] = bounds;
    if (this.geographic) {
      const a = lonLatToWorld(minx, miny);
      const b = lonLatToWorld(maxx, maxy);
      minx = Math.min(a[0], b[0]); miny = Math.min(a[1], b[1]);
      maxx = Math.max(a[0], b[0]); maxy = Math.max(a[1], b[1]);
    }
    const pad = padding === undefined ? 40 : padding;
    const spanX = Math.max(maxx - minx, 1e-6);
    const spanY = Math.max(maxy - miny, 1e-6);
    this.centre = [(minx + maxx) / 2, (miny + maxy) / 2];
    this.scale = Math.min(
      (this.width - 2 * pad) / spanX,
      (this.height - 2 * pad) / spanY
    );
    if (!Number.isFinite(this.scale) || this.scale <= 0) this.scale = 1;
    this.draw();
    this.onViewChange(this.viewBounds());
  }

  centreOn(lonLatOrXY, keepScale) {
    const point = this.geographic
      ? lonLatToWorld(lonLatOrXY[0], lonLatOrXY[1])
      : lonLatOrXY;
    this.centre = [point[0], point[1]];
    if (!keepScale) this.scale = Math.max(this.scale, 1.2);
    this.draw();
    this.onViewChange(this.viewBounds());
  }

  toScreen(wx, wy) {
    return [
      (wx - this.centre[0]) * this.scale + this.width / 2,
      this.height / 2 - (wy - this.centre[1]) * this.scale,
    ];
  }

  toWorld(sx, sy) {
    return [
      (sx - this.width / 2) / this.scale + this.centre[0],
      this.centre[1] - (sy - this.height / 2) / this.scale,
    ];
  }

  /** Current viewport in the coordinates the API speaks (lon/lat or local). */
  viewBounds() {
    const a = this.toWorld(0, this.height);
    const b = this.toWorld(this.width, 0);
    if (!this.geographic) return [a[0], a[1], b[0], b[1]];
    const p = worldToLonLat(a[0], a[1]);
    const q = worldToLonLat(b[0], b[1]);
    return [p[0], p[1], q[0], q[1]];
  }

  zoomBy(factor, anchorX, anchorY) {
    const ax = anchorX === undefined ? this.width / 2 : anchorX;
    const ay = anchorY === undefined ? this.height / 2 : anchorY;
    const before = this.toWorld(ax, ay);
    this.scale = Math.max(1e-9, Math.min(this.scale * factor, 1e5));
    const after = this.toWorld(ax, ay);
    this.centre = [
      this.centre[0] + (before[0] - after[0]),
      this.centre[1] + (before[1] - after[1]),
    ];
    this.draw();
    this.onViewChange(this.viewBounds());
  }

  setBasemap(url, enabled) {
    this.basemapUrl = url || '';
    this.basemapEnabled = !!enabled && !!url && this.geographic;
    this.draw();
  }

  /* -- drawing ------------------------------------------------------------- */

  draw() {
    if (this._frame) return;
    this._frame = requestAnimationFrame(() => {
      this._frame = null;
      this._render();
    });
  }

  _render() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.fillStyle = '#0c111b';
    ctx.fillRect(0, 0, this.width, this.height);
    if (this.basemapEnabled) this._drawTiles();
    this._drawLinks();
  }

  _drawTiles() {
    const worldPixels = 2 * MERC_HALF * this.scale;
    let z = Math.round(Math.log2(worldPixels / TILE_SIZE));
    z = Math.max(0, Math.min(19, z));
    const n = Math.pow(2, z);
    const tileWorld = (2 * MERC_HALF) / n;
    const topLeft = this.toWorld(0, 0);
    const bottomRight = this.toWorld(this.width, this.height);
    const x0 = Math.floor((topLeft[0] + MERC_HALF) / tileWorld);
    const x1 = Math.ceil((bottomRight[0] + MERC_HALF) / tileWorld);
    const y0 = Math.floor((MERC_HALF - topLeft[1]) / tileWorld);
    const y1 = Math.ceil((MERC_HALF - bottomRight[1]) / tileWorld);
    const size = tileWorld * this.scale;

    for (let ty = y0; ty < y1; ty += 1) {
      if (ty < 0 || ty >= n) continue;
      for (let tx = x0; tx < x1; tx += 1) {
        const wrapped = ((tx % n) + n) % n;
        const image = this._tile(z, wrapped, ty);
        if (!image || !image.complete || !image.naturalWidth) continue;
        const [sx, sy] = this.toScreen(
          tx * tileWorld - MERC_HALF,
          MERC_HALF - ty * tileWorld
        );
        this.ctx.drawImage(image, sx, sy, size + 1, size + 1);
      }
    }
  }

  _tile(z, x, y) {
    const id = z + '/' + x + '/' + y;
    let image = this._tiles.get(id);
    if (image) return image;
    if (this._tiles.size > 400) {
      // Cheap cache eviction: drop the oldest quarter.
      const keys = Array.from(this._tiles.keys()).slice(0, 100);
      keys.forEach((key) => this._tiles.delete(key));
    }
    image = new Image();
    image.crossOrigin = 'anonymous';
    image.onload = () => this.draw();
    image.onerror = () => { image.failed = true; };
    image.src = this.basemapUrl
      .replace('{z}', z).replace('{x}', x).replace('{y}', y)
      .replace('{s}', 'abc'[(x + y) % 3]);
    this._tiles.set(id, image);
    return image;
  }

  _widthOf(item) {
    if (!this.showBands || item.value === null) return 3;
    const ratio = Math.sqrt(Math.max(0, item.value) / this.maxValue);
    return 2.5 + 15 * ratio;
  }

  _colourOf(item) {
    if (item.data.status === 'flagged') return COLOR_FLAGGED;
    if (item.value === null) return COLOR_EMPTY;
    const ratio = Math.max(0, Math.min(1, item.value / this.maxValue));
    return RAMP[Math.min(RAMP.length - 1, Math.floor(ratio * RAMP.length))];
  }

  /** Project a link and offset it to the right of the travel direction. */
  _screenPath(item, offset) {
    const world = item.world;
    const count = world.length / 2;
    const points = new Array(count);
    for (let i = 0; i < count; i += 1) {
      points[i] = this.toScreen(world[i * 2], world[i * 2 + 1]);
    }
    if (offset === 0) return points;
    const out = new Array(count);
    for (let i = 0; i < count; i += 1) {
      let nx = 0;
      let ny = 0;
      // Average the right hand normals of the adjacent segments.
      for (const [a, b] of [[i - 1, i], [i, i + 1]]) {
        if (a < 0 || b >= count) continue;
        const dx = points[b][0] - points[a][0];
        const dy = points[b][1] - points[a][1];
        const len = Math.hypot(dx, dy);
        if (len < 1e-9) continue;
        // Screen y points down, so rotating the direction by +90 degrees
        // (x, y) -> (-y, x) yields the right hand side of the travel direction.
        nx += -dy / len;
        ny += dx / len;
      }
      const len = Math.hypot(nx, ny);
      if (len < 1e-9) {
        out[i] = points[i];
      } else {
        out[i] = [points[i][0] + (nx / len) * offset, points[i][1] + (ny / len) * offset];
      }
    }
    return out;
  }

  _drawLinks() {
    const ctx = this.ctx;
    const view = this.toWorld(0, this.height);
    const view2 = this.toWorld(this.width, 0);
    const margin = 200 / this.scale;
    const vminx = view[0] - margin;
    const vminy = view[1] - margin;
    const vmaxx = view2[0] + margin;
    const vmaxy = view2[1] + margin;

    const visible = [];
    for (const item of this.items) {
      const b = item.bbox;
      if (b[2] < vminx || b[0] > vmaxx || b[3] < vminy || b[1] > vmaxy) {
        item.screen = null;
        continue;
      }
      const width = this._widthOf(item);
      item.screen = this._screenPath(item, width / 2 + 1.5);
      item.width = width;
      visible.push(item);
    }
    this.visible = visible;

    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    // Two passes so that filled directions stay readable over the grey ones.
    for (const pass of [0, 1]) {
      for (const item of visible) {
        const filled = item.value !== null || item.data.status === 'flagged';
        if ((pass === 0) === filled) continue;
        this._strokePath(item.screen, this._colourOf(item), item.width);
      }
    }

    for (const item of visible) {
      if (item.width >= 3 && this.scale * 40 > 1) this._drawArrow(item);
    }
    // Highlights go on before the labels so that a selected direction never
    // paints over its own value.
    for (const key of [this.hoverKey, this.selectedKey]) {
      const item = key && this.byKey.get(key);
      if (!item || !item.screen) continue;
      this._strokePath(item.screen, COLOR_SELECTED, item.width + 4, 0.9);
      this._strokePath(item.screen, this._colourOf(item), item.width);
      this._drawArrow(item);
    }
    if (this.showLabels) this._drawLabels(visible);
  }

  _strokePath(points, colour, width, alpha) {
    if (!points || points.length < 2) return;
    const ctx = this.ctx;
    ctx.globalAlpha = alpha === undefined ? 1 : alpha;
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    for (let i = 1; i < points.length; i += 1) ctx.lineTo(points[i][0], points[i][1]);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  _drawArrow(item) {
    const points = item.screen;
    if (!points || points.length < 2) return;
    const end = points[points.length - 1];
    const prev = points[points.length - 2];
    const dx = end[0] - prev[0];
    const dy = end[1] - prev[1];
    const len = Math.hypot(dx, dy);
    if (len < 12) return;
    const ux = dx / len;
    const uy = dy / len;
    // Sit the head a little before the node so that arrows do not pile up.
    const tipX = end[0] - ux * 6;
    const tipY = end[1] - uy * 6;
    const size = Math.max(5, Math.min(9, item.width + 3));
    const ctx = this.ctx;
    ctx.fillStyle = this._colourOf(item);
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(tipX - ux * size - uy * size * 0.5, tipY - uy * size + ux * size * 0.5);
    ctx.lineTo(tipX - ux * size + uy * size * 0.5, tipY - uy * size - ux * size * 0.5);
    ctx.closePath();
    ctx.fill();
  }

  _drawLabels(visible) {
    const ctx = this.ctx;
    ctx.font = '600 11px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineWidth = 3;
    ctx.strokeStyle = 'rgba(8,12,20,.85)';

    // Labels of the two directions of one link would otherwise land on top of
    // each other, so each is pushed further out to its own side and anything
    // that still collides is dropped rather than drawn illegibly.
    const placed = [];
    let drawn = 0;
    for (const item of visible) {
      if (item.value === null || drawn >= 400) continue;
      const points = item.screen;
      if (!points || points.length < 2) continue;
      const start = points[0];
      const end = points[points.length - 1];
      if (Math.hypot(end[0] - start[0], end[1] - start[1]) < 34) continue;

      const index = Math.max(1, Math.floor(points.length / 2));
      const a = points[index - 1];
      const b = points[index];
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const len = Math.hypot(dx, dy) || 1;
      const push = item.width / 2 + 8;
      const cx = (a[0] + b[0]) / 2 + (-dy / len) * push;
      const cy = (a[1] + b[1]) / 2 + (dx / len) * push;

      const text = item.value.toLocaleString('cs-CZ');
      const half = ctx.measureText(text).width / 2 + 2;
      const box = [cx - half, cy - 7, cx + half, cy + 7];
      if (placed.some((other) => overlaps(box, other))) continue;
      placed.push(box);

      ctx.strokeText(text, cx, cy);
      ctx.fillStyle = '#eef3fa';
      ctx.fillText(text, cx, cy);
      drawn += 1;
    }
  }

  /* -- interaction --------------------------------------------------------- */

  pick(sx, sy) {
    const threshold = 9;
    let best = null;
    let bestDistance = threshold;
    for (const item of this.visible || []) {
      const points = item.screen;
      if (!points) continue;
      const tolerance = Math.max(threshold, item.width / 2 + 3);
      for (let i = 1; i < points.length; i += 1) {
        const d = distanceToSegment(sx, sy, points[i - 1], points[i]);
        if (d < tolerance && d < bestDistance) {
          bestDistance = d;
          best = item;
        }
      }
    }
    return best;
  }

  select(key, centre) {
    this.selectedKey = key;
    if (centre && key) {
      const item = this.byKey.get(key);
      if (item) {
        const count = item.world.length / 2;
        const i = Math.floor(count / 2);
        this.centre = [item.world[i * 2], item.world[i * 2 + 1]];
        this.onViewChange(this.viewBounds());
      }
    }
    this.draw();
  }

  _bindEvents() {
    const canvas = this.canvas;

    canvas.addEventListener('pointerdown', (event) => {
      canvas.setPointerCapture(event.pointerId);
      this._pointers.set(event.pointerId, [event.offsetX, event.offsetY]);
      this._moved = false;
      this._dragFrom = [event.offsetX, event.offsetY];
      this._dragCentre = this.centre.slice();
      canvas.classList.add('dragging');
    });

    canvas.addEventListener('pointermove', (event) => {
      if (!this._pointers.has(event.pointerId)) {
        const hit = this.pick(event.offsetX, event.offsetY);
        const key = hit ? hit.key : null;
        if (key !== this.hoverKey) {
          this.hoverKey = key;
          canvas.title = hit ? this._tooltip(hit) : '';
          this.draw();
        }
        return;
      }
      this._pointers.set(event.pointerId, [event.offsetX, event.offsetY]);
      if (this._pointers.size >= 2) {
        this._handlePinch();
        return;
      }
      const dx = event.offsetX - this._dragFrom[0];
      const dy = event.offsetY - this._dragFrom[1];
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) this._moved = true;
      this.centre = [
        this._dragCentre[0] - dx / this.scale,
        this._dragCentre[1] + dy / this.scale,
      ];
      this.draw();
    });

    const release = (event) => {
      if (!this._pointers.has(event.pointerId)) return;
      this._pointers.delete(event.pointerId);
      this._pinchDistance = 0;
      canvas.classList.remove('dragging');
      if (!this._moved) {
        const hit = this.pick(event.offsetX, event.offsetY);
        this.selectedKey = hit ? hit.key : null;
        this.draw();
        this.onSelect(hit ? hit.data : null);
      } else {
        this.onViewChange(this.viewBounds());
      }
    };
    canvas.addEventListener('pointerup', release);
    canvas.addEventListener('pointercancel', (event) => {
      this._pointers.delete(event.pointerId);
      canvas.classList.remove('dragging');
    });

    canvas.addEventListener('wheel', (event) => {
      event.preventDefault();
      const factor = Math.pow(1.0015, -event.deltaY);
      this.zoomBy(factor, event.offsetX, event.offsetY);
    }, { passive: false });

    canvas.addEventListener('dblclick', (event) => {
      this.zoomBy(2, event.offsetX, event.offsetY);
    });

    canvas.addEventListener('contextmenu', (event) => event.preventDefault());
  }

  _handlePinch() {
    const points = Array.from(this._pointers.values());
    const distance = Math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1]);
    const cx = (points[0][0] + points[1][0]) / 2;
    const cy = (points[0][1] + points[1][1]) / 2;
    if (this._pinchDistance > 0 && distance > 0) {
      this.zoomBy(distance / this._pinchDistance, cx, cy);
    }
    this._pinchDistance = distance;
    this._moved = true;
  }

  _tooltip(item) {
    const link = item.data;
    const parts = ['Link ' + link.link_no + ': ' + link.from_node + ' → ' + link.to_node];
    if (link.name) parts.push(link.name);
    if (item.value !== null) parts.push(this.valueField + ' = ' + item.value);
    return parts.join('\n');
  }
}

function overlaps(a, b) {
  return !(a[2] < b[0] || a[0] > b[2] || a[3] < b[1] || a[1] > b[3]);
}

function distanceToSegment(px, py, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared < 1e-12) return Math.hypot(px - a[0], py - a[1]);
  let t = ((px - a[0]) * dx + (py - a[1]) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy));
}

window.TrafficMap = TrafficMap;
window.trafficMapHelpers = { lonLatToWorld, worldToLonLat, RAMP, COLOR_EMPTY, COLOR_FLAGGED };
