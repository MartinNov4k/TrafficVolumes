"""Coordinate transformations from a Visum network CRS to WGS84.

Visum networks in Czechia are normally stored in S-JTSK / Krovak East North
(EPSG:5514) or in the older southing/westing flavour (EPSG:5513, EPSG:2065).
Both are implemented here in pure Python so that the tool runs without any
third party package.  Anything else is delegated to ``pyproj`` when available,
and otherwise the coordinates are kept as they are and the map falls back to a
plain cartesian view without a background map.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

# --- Bessel 1841 / Krovak constants -----------------------------------------

_A = 6377397.155
_E2 = 0.006674372230614
_E = math.sqrt(_E2)
_PHI_C = math.radians(49.5)                    # latitude of projection centre
_LAMBDA_0 = math.radians(24.83333333333333)    # longitude of origin (EPSG parameter)
_ALPHA_C = math.radians(30.28813975277778)     # co-latitude of the cone axis
_PHI_P = math.radians(78.5)                    # pseudo standard parallel
_KP = 0.9999

_A_K = _A * math.sqrt(1.0 - _E2) / (1.0 - _E2 * math.sin(_PHI_C) ** 2)
_B_K = math.sqrt(1.0 + (_E2 * math.cos(_PHI_C) ** 4) / (1.0 - _E2))
_GAMMA_0 = math.asin(math.sin(_PHI_C) / _B_K)
_T_0 = (
    math.tan(math.pi / 4.0 + _GAMMA_0 / 2.0)
    * ((1.0 + _E * math.sin(_PHI_C)) / (1.0 - _E * math.sin(_PHI_C))) ** (_E * _B_K / 2.0)
    / math.tan(math.pi / 4.0 + _PHI_C / 2.0) ** _B_K
)
_N_K = math.sin(_PHI_P)
_R_0 = _KP * _A_K / math.tan(_PHI_P)

EARTH_RADIUS = 6378137.0
MERCATOR_HALF_WORLD = math.pi * EARTH_RADIUS


# --- Bessel 1841 (S-JTSK) <-> WGS84 datum shift ------------------------------
#
# Seven parameter Helmert transformation, position vector convention, as used by
# PROJ for S-JTSK (+towgs84=570.8,85.7,462.8,4.998,1.587,5.261,3.56).  Without
# it the network would sit roughly 100-200 m away from any background map.

_HELMERT_T = (570.8, 85.7, 462.8)
_HELMERT_R = tuple(math.radians(v / 3600.0) for v in (4.998, 1.587, 5.261))
_HELMERT_S = 3.56e-6

_BESSEL_A = 6377397.155
_BESSEL_F = 1.0 / 299.1528128
_WGS_A = 6378137.0
_WGS_F = 1.0 / 298.257223563


def _geodetic_to_geocentric(lon: float, lat: float, a: float, f: float) -> Tuple[float, float, float]:
    e2 = f * (2.0 - f)
    phi, lam = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1.0 - e2 * math.sin(phi) ** 2)
    return (
        n * math.cos(phi) * math.cos(lam),
        n * math.cos(phi) * math.sin(lam),
        n * (1.0 - e2) * math.sin(phi),
    )


def _geocentric_to_geodetic(x: float, y: float, z: float, a: float, f: float) -> Tuple[float, float]:
    e2 = f * (2.0 - f)
    lam = math.atan2(y, x)
    p = math.hypot(x, y)
    phi = math.atan2(z, p * (1.0 - e2))
    for _ in range(8):
        n = a / math.sqrt(1.0 - e2 * math.sin(phi) ** 2)
        prev = phi
        phi = math.atan2(z + e2 * n * math.sin(phi), p)
        if abs(phi - prev) < 1e-13:
            break
    return math.degrees(lam), math.degrees(phi)


def _helmert(x: float, y: float, z: float, inverse: bool) -> Tuple[float, float, float]:
    tx, ty, tz = _HELMERT_T
    rx, ry, rz = _HELMERT_R
    scale = 1.0 + _HELMERT_S
    if not inverse:
        return (
            tx + scale * (x - rz * y + ry * z),
            ty + scale * (rz * x + y - rx * z),
            tz + scale * (-ry * x + rx * y + z),
        )
    dx, dy, dz = (x - tx) / scale, (y - ty) / scale, (z - tz) / scale
    return (
        dx + rz * dy - ry * dz,
        -rz * dx + dy + rx * dz,
        ry * dx - rx * dy + dz,
    )


def bessel_to_wgs84(lon: float, lat: float) -> Tuple[float, float]:
    x, y, z = _geodetic_to_geocentric(lon, lat, _BESSEL_A, _BESSEL_F)
    x, y, z = _helmert(x, y, z, inverse=False)
    return _geocentric_to_geodetic(x, y, z, _WGS_A, _WGS_F)


def wgs84_to_bessel(lon: float, lat: float) -> Tuple[float, float]:
    x, y, z = _geodetic_to_geocentric(lon, lat, _WGS_A, _WGS_F)
    x, y, z = _helmert(x, y, z, inverse=True)
    return _geocentric_to_geodetic(x, y, z, _BESSEL_A, _BESSEL_F)


def krovak_to_bessel(southing: float, westing: float) -> Tuple[float, float]:
    """Krovak southing/westing to (lon, lat) on the Bessel 1841 ellipsoid."""
    r = math.hypot(southing, westing)
    if r == 0.0:
        raise ValueError("Krovak origin cannot be transformed")
    theta = math.atan2(westing, southing)
    d = theta / _N_K
    t = 2.0 * (
        math.atan(
            (_R_0 / r) ** (1.0 / _N_K) * math.tan(math.pi / 4.0 + _PHI_P / 2.0)
        )
        - math.pi / 4.0
    )
    u = math.asin(
        math.cos(_ALPHA_C) * math.sin(t) - math.sin(_ALPHA_C) * math.cos(t) * math.cos(d)
    )
    v = math.asin(math.cos(t) * math.sin(d) / math.cos(u))

    phi = u
    for _ in range(12):
        prev = phi
        phi = 2.0 * (
            math.atan(
                _T_0 ** (-1.0 / _B_K)
                * math.tan(u / 2.0 + math.pi / 4.0) ** (1.0 / _B_K)
                * ((1.0 + _E * math.sin(phi)) / (1.0 - _E * math.sin(phi))) ** (_E / 2.0)
            )
            - math.pi / 4.0
        )
        if abs(phi - prev) < 1e-13:
            break
    lam = _LAMBDA_0 - v / _B_K
    return math.degrees(lam), math.degrees(phi)


def krovak_to_wgs84(southing: float, westing: float) -> Tuple[float, float]:
    """Convert S-JTSK Krovak southing/westing (EPSG:5513) to WGS84 (lon, lat)."""
    return bessel_to_wgs84(*krovak_to_bessel(southing, westing))


def wgs84_to_krovak(lon: float, lat: float) -> Tuple[float, float]:
    """Convert WGS84 (lon, lat) to S-JTSK Krovak southing/westing (EPSG:5513)."""
    lon, lat = wgs84_to_bessel(lon, lat)
    phi = math.radians(lat)
    lam = math.radians(lon)
    u = 2.0 * (
        math.atan(
            _T_0
            * math.tan(phi / 2.0 + math.pi / 4.0) ** _B_K
            / ((1.0 + _E * math.sin(phi)) / (1.0 - _E * math.sin(phi))) ** (_E * _B_K / 2.0)
        )
        - math.pi / 4.0
    )
    v = _B_K * (_LAMBDA_0 - lam)
    t = math.asin(
        math.cos(_ALPHA_C) * math.sin(u) + math.sin(_ALPHA_C) * math.cos(u) * math.cos(v)
    )
    d = math.asin(math.cos(u) * math.sin(v) / math.cos(t))
    theta = _N_K * d
    r = (
        _R_0
        * math.tan(math.pi / 4.0 + _PHI_P / 2.0) ** _N_K
        / math.tan(math.pi / 4.0 + t / 2.0) ** _N_K
    )
    return r * math.cos(theta), r * math.sin(theta)


def web_mercator_to_wgs84(x: float, y: float) -> Tuple[float, float]:
    lon = x / EARTH_RADIUS
    lat = 2.0 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2.0
    return math.degrees(lon), math.degrees(lat)


def wgs84_to_web_mercator(lon: float, lat: float) -> Tuple[float, float]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = math.radians(lon) * EARTH_RADIUS
    y = math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)) * EARTH_RADIUS
    return x, y


# --- CRS registry ------------------------------------------------------------

#: CRS identifiers understood without any third party package.
BUILTIN_CRS = {
    "wgs84": "EPSG:4326",
    "epsg:4326": "EPSG:4326",
    "epsg:5514": "EPSG:5514",
    "epsg:5513": "EPSG:5513",
    "epsg:2065": "EPSG:5513",
    "s-jtsk": "EPSG:5514",
    "sjtsk": "EPSG:5514",
    "krovak": "EPSG:5514",
    "epsg:3857": "EPSG:3857",
    "epsg:900913": "EPSG:3857",
    "webmercator": "EPSG:3857",
    "local": "LOCAL",
    "none": "LOCAL",
}


class ProjectionError(RuntimeError):
    pass


@dataclass
class Projector:
    """Transforms source coordinates into the coordinates the map works with.

    ``mode`` is ``"geographic"`` when the result is (lon, lat) in WGS84 and
    ``"local"`` when the source coordinates are passed through unchanged.  In
    local mode the browser shows a plain cartesian canvas without a background
    map, which keeps unknown or project specific coordinate systems usable.
    """

    crs: str
    mode: str
    _fn: Optional[Callable[[float, float], Tuple[float, float]]] = None

    def __call__(self, x: float, y: float) -> Tuple[float, float]:
        if self._fn is None:
            return x, y
        return self._fn(x, y)

    def transform_many(
        self, points: Iterable[Sequence[float]]
    ) -> List[Tuple[float, float]]:
        return [self(float(p[0]), float(p[1])) for p in points]


def _pyproj_projector(crs: str) -> Optional[Projector]:
    try:
        from pyproj import Transformer  # type: ignore
    except Exception:
        return None
    try:
        tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    except Exception as exc:  # pragma: no cover - depends on pyproj database
        raise ProjectionError(f"pyproj cannot handle CRS {crs!r}: {exc}") from exc

    def fn(x: float, y: float) -> Tuple[float, float]:
        lon, lat = tr.transform(x, y)
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ProjectionError(f"CRS {crs!r} produced an invalid coordinate")
        return lon, lat

    return Projector(crs=crs, mode="geographic", _fn=fn)


def get_projector(crs: Optional[str]) -> Projector:
    """Build a :class:`Projector` for ``crs``.

    ``crs`` may be ``None`` or ``"auto"``, in which case the caller is expected
    to have resolved the CRS with :func:`detect_crs` first; the value is then
    treated as ``local``.
    """
    key = (crs or "local").strip().lower()
    resolved = BUILTIN_CRS.get(key)

    if resolved == "EPSG:4326":
        return Projector(crs="EPSG:4326", mode="geographic", _fn=None)
    if resolved == "EPSG:5514":
        # East North axis order: easting = -westing, northing = -southing.
        return Projector(
            crs="EPSG:5514",
            mode="geographic",
            _fn=lambda x, y: krovak_to_wgs84(-y, -x),
        )
    if resolved == "EPSG:5513":
        # Historic axis order, first ordinate is southing and second is westing.
        return Projector(
            crs="EPSG:5513",
            mode="geographic",
            _fn=lambda x, y: krovak_to_wgs84(x, y),
        )
    if resolved == "EPSG:3857":
        return Projector(crs="EPSG:3857", mode="geographic", _fn=web_mercator_to_wgs84)
    if resolved == "LOCAL":
        return Projector(crs="LOCAL", mode="local", _fn=None)

    projector = _pyproj_projector(crs or "")
    if projector is None:
        raise ProjectionError(
            f"CRS {crs!r} is not built in and pyproj is not installed. "
            "Install pyproj, or re-run with --crs local to use a plain cartesian view."
        )
    return projector


def detect_crs(samples: Sequence[Tuple[float, float]]) -> str:
    """Guess the CRS of a network from a handful of coordinates."""
    pts = [(float(x), float(y)) for x, y in samples if _finite(x) and _finite(y)]
    if not pts:
        return "local"

    def frac(pred: Callable[[float, float], bool]) -> float:
        return sum(1 for x, y in pts if pred(x, y)) / len(pts)

    if frac(lambda x, y: abs(x) <= 180.0 and abs(y) <= 90.0) > 0.98:
        return "wgs84"
    # EPSG:5514 keeps both ordinates negative over Czechia and Slovakia.
    if frac(lambda x, y: -950000 < x < -400000 and -1300000 < y < -900000) > 0.9:
        return "epsg:5514"
    # EPSG:5513 / 2065 southing-westing, both ordinates positive.
    if frac(lambda x, y: 900000 < x < 1300000 and 400000 < y < 950000) > 0.9:
        return "epsg:5513"
    if frac(lambda x, y: abs(x) <= MERCATOR_HALF_WORLD and abs(y) <= MERCATOR_HALF_WORLD) > 0.98:
        # Ambiguous with many national grids, so only trust it for large values.
        if frac(lambda x, y: abs(x) > 1400000 or abs(y) > 1400000) > 0.9:
            return "epsg:3857"
    return "local"


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
