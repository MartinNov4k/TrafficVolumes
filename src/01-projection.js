/* Coordinate transformations, ported from the Python implementation.
 *
 * S-JTSK / Krovak (EPSG:5514 and the older southing-westing 5513/2065) is
 * implemented directly because that is what Czech Visum networks use, and a
 * browser has no PROJ to fall back on. Verified against the EPSG 9819 worked
 * example and against PROJ.
 */
(function (TV) {
  'use strict';

  var A = 6377397.155;
  var E2 = 0.006674372230614;
  var E = Math.sqrt(E2);
  var PHI_C = 49.5 * Math.PI / 180;
  var LAMBDA_0 = 24.83333333333333 * Math.PI / 180;
  var ALPHA_C = 30.28813975277778 * Math.PI / 180;
  var PHI_P = 78.5 * Math.PI / 180;
  var KP = 0.9999;

  var A_K = A * Math.sqrt(1 - E2) / (1 - E2 * Math.pow(Math.sin(PHI_C), 2));
  var B_K = Math.sqrt(1 + (E2 * Math.pow(Math.cos(PHI_C), 4)) / (1 - E2));
  var GAMMA_0 = Math.asin(Math.sin(PHI_C) / B_K);
  var T_0 = Math.tan(Math.PI / 4 + GAMMA_0 / 2)
    * Math.pow((1 + E * Math.sin(PHI_C)) / (1 - E * Math.sin(PHI_C)), E * B_K / 2)
    / Math.pow(Math.tan(Math.PI / 4 + PHI_C / 2), B_K);
  var N_K = Math.sin(PHI_P);
  var R_0 = KP * A_K / Math.tan(PHI_P);

  var EARTH_R = 6378137.0;
  var MERC_HALF = Math.PI * EARTH_R;

  // Seven parameter Helmert, position vector convention, as PROJ uses for
  // S-JTSK (+towgs84=570.8,85.7,462.8,4.998,1.587,5.261,3.56). Without it the
  // network sits 100-200 m away from any background map.
  var HT = [570.8, 85.7, 462.8];
  var HR = [4.998, 1.587, 5.261].map(function (v) { return v / 3600 * Math.PI / 180; });
  var HS = 3.56e-6;
  var BESSEL = { a: 6377397.155, f: 1 / 299.1528128 };
  var WGS = { a: 6378137.0, f: 1 / 298.257223563 };

  function geodeticToGeocentric(lon, lat, ell) {
    var e2 = ell.f * (2 - ell.f);
    var phi = lat * Math.PI / 180;
    var lam = lon * Math.PI / 180;
    var n = ell.a / Math.sqrt(1 - e2 * Math.pow(Math.sin(phi), 2));
    return [
      n * Math.cos(phi) * Math.cos(lam),
      n * Math.cos(phi) * Math.sin(lam),
      n * (1 - e2) * Math.sin(phi)
    ];
  }

  function geocentricToGeodetic(x, y, z, ell) {
    var e2 = ell.f * (2 - ell.f);
    var lam = Math.atan2(y, x);
    var p = Math.sqrt(x * x + y * y);
    var phi = Math.atan2(z, p * (1 - e2));
    for (var i = 0; i < 8; i += 1) {
      var n = ell.a / Math.sqrt(1 - e2 * Math.pow(Math.sin(phi), 2));
      var previous = phi;
      phi = Math.atan2(z + e2 * n * Math.sin(phi), p);
      if (Math.abs(phi - previous) < 1e-13) break;
    }
    return [lam * 180 / Math.PI, phi * 180 / Math.PI];
  }

  function helmert(x, y, z, inverse) {
    var scale = 1 + HS;
    if (!inverse) {
      return [
        HT[0] + scale * (x - HR[2] * y + HR[1] * z),
        HT[1] + scale * (HR[2] * x + y - HR[0] * z),
        HT[2] + scale * (-HR[1] * x + HR[0] * y + z)
      ];
    }
    var dx = (x - HT[0]) / scale;
    var dy = (y - HT[1]) / scale;
    var dz = (z - HT[2]) / scale;
    return [
      dx + HR[2] * dy - HR[1] * dz,
      -HR[2] * dx + dy + HR[0] * dz,
      HR[1] * dx - HR[0] * dy + dz
    ];
  }

  function besselToWgs84(lon, lat) {
    var p = geodeticToGeocentric(lon, lat, BESSEL);
    var q = helmert(p[0], p[1], p[2], false);
    return geocentricToGeodetic(q[0], q[1], q[2], WGS);
  }

  function wgs84ToBessel(lon, lat) {
    var p = geodeticToGeocentric(lon, lat, WGS);
    var q = helmert(p[0], p[1], p[2], true);
    return geocentricToGeodetic(q[0], q[1], q[2], BESSEL);
  }

  /** Krovak southing/westing to (lon, lat) on the Bessel 1841 ellipsoid. */
  function krovakToBessel(southing, westing) {
    var r = Math.sqrt(southing * southing + westing * westing);
    if (r === 0) throw new Error('Krovak origin cannot be transformed');
    var theta = Math.atan2(westing, southing);
    var d = theta / N_K;
    var t = 2 * (Math.atan(
      Math.pow(R_0 / r, 1 / N_K) * Math.tan(Math.PI / 4 + PHI_P / 2)
    ) - Math.PI / 4);
    var u = Math.asin(
      Math.cos(ALPHA_C) * Math.sin(t) - Math.sin(ALPHA_C) * Math.cos(t) * Math.cos(d)
    );
    var v = Math.asin(Math.cos(t) * Math.sin(d) / Math.cos(u));

    var phi = u;
    for (var i = 0; i < 12; i += 1) {
      var previous = phi;
      phi = 2 * (Math.atan(
        Math.pow(T_0, -1 / B_K)
        * Math.pow(Math.tan(u / 2 + Math.PI / 4), 1 / B_K)
        * Math.pow((1 + E * Math.sin(phi)) / (1 - E * Math.sin(phi)), E / 2)
      ) - Math.PI / 4);
      if (Math.abs(phi - previous) < 1e-13) break;
    }
    return [(LAMBDA_0 - v / B_K) * 180 / Math.PI, phi * 180 / Math.PI];
  }

  function krovakToWgs84(southing, westing) {
    var p = krovakToBessel(southing, westing);
    return besselToWgs84(p[0], p[1]);
  }

  function wgs84ToKrovak(lon, lat) {
    var g = wgs84ToBessel(lon, lat);
    var phi = g[1] * Math.PI / 180;
    var lam = g[0] * Math.PI / 180;
    var u = 2 * (Math.atan(
      T_0 * Math.pow(Math.tan(phi / 2 + Math.PI / 4), B_K)
      / Math.pow((1 + E * Math.sin(phi)) / (1 - E * Math.sin(phi)), E * B_K / 2)
    ) - Math.PI / 4);
    var v = B_K * (LAMBDA_0 - lam);
    var t = Math.asin(
      Math.cos(ALPHA_C) * Math.sin(u) + Math.sin(ALPHA_C) * Math.cos(u) * Math.cos(v)
    );
    var d = Math.asin(Math.cos(u) * Math.sin(v) / Math.cos(t));
    var theta = N_K * d;
    var r = R_0 * Math.pow(Math.tan(Math.PI / 4 + PHI_P / 2), N_K)
      / Math.pow(Math.tan(Math.PI / 4 + t / 2), N_K);
    return [r * Math.cos(theta), r * Math.sin(theta)];
  }

  function webMercatorToWgs84(x, y) {
    return [
      (x / EARTH_R) * 180 / Math.PI,
      (2 * Math.atan(Math.exp(y / EARTH_R)) - Math.PI / 2) * 180 / Math.PI
    ];
  }

  function wgs84ToWebMercator(lon, lat) {
    var clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
    return [
      (lon * Math.PI / 180) * EARTH_R,
      Math.log(Math.tan(Math.PI / 4 + (clamped * Math.PI / 180) / 2)) * EARTH_R
    ];
  }

  /** Coordinate systems the app can place on a real map without any library. */
  var CRS_LIST = [
    { id: 'auto', label: 'Rozpoznat automaticky' },
    { id: 'epsg:5514', label: 'S-JTSK / Krovák East North (EPSG:5514)' },
    { id: 'epsg:5513', label: 'S-JTSK / Krovák jih-západ (EPSG:5513, 2065)' },
    { id: 'wgs84', label: 'WGS84 zeměpisné souřadnice (EPSG:4326)' },
    { id: 'epsg:3857', label: 'Web Mercator (EPSG:3857)' },
    { id: 'local', label: 'Neznámý / místní systém (rovinné plátno)' }
  ];

  /** Build a transform from source coordinates to (lon, lat), or a passthrough. */
  function getProjector(crs) {
    var key = String(crs || 'local').toLowerCase();
    if (key === 'wgs84' || key === 'epsg:4326') {
      return { crs: 'EPSG:4326', mode: 'geographic', fn: function (x, y) { return [x, y]; } };
    }
    if (key === 'epsg:5514' || key === 's-jtsk' || key === 'krovak') {
      // East North axis order: easting = -westing, northing = -southing.
      return {
        crs: 'EPSG:5514', mode: 'geographic',
        fn: function (x, y) { return krovakToWgs84(-y, -x); }
      };
    }
    if (key === 'epsg:5513' || key === 'epsg:2065') {
      return {
        crs: 'EPSG:5513', mode: 'geographic',
        fn: function (x, y) { return krovakToWgs84(x, y); }
      };
    }
    if (key === 'epsg:3857' || key === 'webmercator') {
      return { crs: 'EPSG:3857', mode: 'geographic', fn: webMercatorToWgs84 };
    }
    return { crs: 'LOCAL', mode: 'local', fn: function (x, y) { return [x, y]; } };
  }

  /** Guess the coordinate system from a handful of sample coordinates. */
  function detectCrs(samples) {
    var points = samples.filter(function (p) {
      return isFinite(p[0]) && isFinite(p[1]);
    });
    if (!points.length) return 'local';

    function fraction(predicate) {
      var hits = 0;
      for (var i = 0; i < points.length; i += 1) {
        if (predicate(points[i][0], points[i][1])) hits += 1;
      }
      return hits / points.length;
    }

    if (fraction(function (x, y) { return Math.abs(x) <= 180 && Math.abs(y) <= 90; }) > 0.98) {
      return 'wgs84';
    }
    if (fraction(function (x, y) {
      return x > -950000 && x < -400000 && y > -1300000 && y < -900000;
    }) > 0.9) return 'epsg:5514';
    if (fraction(function (x, y) {
      return x > 900000 && x < 1300000 && y > 400000 && y < 950000;
    }) > 0.9) return 'epsg:5513';
    if (fraction(function (x, y) {
      return Math.abs(x) <= MERC_HALF && Math.abs(y) <= MERC_HALF;
    }) > 0.98 && fraction(function (x, y) {
      return Math.abs(x) > 1400000 || Math.abs(y) > 1400000;
    }) > 0.9) return 'epsg:3857';
    return 'local';
  }

  TV.projection = {
    EARTH_R: EARTH_R,
    MERC_HALF: MERC_HALF,
    CRS_LIST: CRS_LIST,
    krovakToBessel: krovakToBessel,
    krovakToWgs84: krovakToWgs84,
    wgs84ToKrovak: wgs84ToKrovak,
    besselToWgs84: besselToWgs84,
    wgs84ToBessel: wgs84ToBessel,
    webMercatorToWgs84: webMercatorToWgs84,
    wgs84ToWebMercator: wgs84ToWebMercator,
    getProjector: getProjector,
    detectCrs: detectCrs
  };
})(typeof globalThis !== 'undefined'
  ? (globalThis.TV = globalThis.TV || {})
  : (this.TV = this.TV || {}));
