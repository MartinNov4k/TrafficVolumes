"""Import Visum link exports into :class:`~trafficvolumes.model.LinkDirection`.

Supported inputs:

* ``*.att`` / ``*.net`` attribute files, including the ``$NODE`` and
  ``$LINKPOLY`` tables of a full network export,
* ``*.csv`` link list exports,
* ``*.geojson`` / ``*.json`` feature collections,
* ``*.shp`` shapefiles when ``pyshp`` is installed.

Geometry is taken from the first source that is available: a ``WKTPOLY``
column, the ``$LINKPOLY`` intermediate points combined with the node
coordinates, the node coordinates alone, or per-row endpoint coordinates.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import visum_att
from .model import LinkDirection, Point

_WKT_RE = re.compile(r"(?:MULTI)?LINESTRING\s*Z?\s*M?\s*\(", re.IGNORECASE)

#: Column name candidates, matched case insensitively after removing spaces.
_ALIASES: Dict[str, Tuple[str, ...]] = {
    "no": ("NO", "LINKNO", "LINK_NO", "ID"),
    "from_node": ("FROMNODENO", "FROM_NODE", "FROMNODE", "ANODE", "NODEFROM"),
    "to_node": ("TONODENO", "TO_NODE", "TONODE", "BNODE", "NODETO"),
    "name": ("NAME", "STREETNAME", "LINKNAME", "NAZEV"),
    "type_no": ("TYPENO", "TYPE", "LINKTYPE", "TYP"),
    "length": ("LENGTH", "LEN", "DELKA"),
    "capacity": ("CAPPRT", "CAPACITY", "CAP", "KAPACITA"),
    "wkt": ("WKTPOLY", "WKT", "GEOMETRY", "THE_GEOM"),
    "x_from": ("FROMNODE\\XCOORD", "XCOORDFROM", "FROMNODEXCOORD", "XFROM", "FROM_X", "X1"),
    "y_from": ("FROMNODE\\YCOORD", "YCOORDFROM", "FROMNODEYCOORD", "YFROM", "FROM_Y", "Y1"),
    "x_to": ("TONODE\\XCOORD", "XCOORDTO", "TONODEXCOORD", "XTO", "TO_X", "X2"),
    "y_to": ("TONODE\\YCOORD", "YCOORDTO", "TONODEYCOORD", "YTO", "TO_Y", "Y2"),
}


class ImportError_(ValueError):
    """Raised when an export cannot be turned into a link network."""


@dataclass
class ImportResult:
    links: List[LinkDirection]
    source_columns: List[str]
    warnings: List[str]
    geometry_source: str


def _norm(name: str) -> str:
    return name.replace(" ", "").replace("_", "").upper()


def _resolve(columns: Sequence[str], role: str) -> Optional[str]:
    lookup = {_norm(c): c for c in columns}
    for candidate in _ALIASES[role]:
        hit = lookup.get(_norm(candidate))
        if hit is not None:
            return hit
    return None


def parse_wkt(text: str) -> List[Point]:
    """Parse a LINESTRING / MULTILINESTRING into a flat list of points."""
    if not text:
        return []
    match = _WKT_RE.search(text)
    if not match:
        return []
    body = text[match.end() - 1 :]
    depth = 0
    end = len(body)
    for index, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = index
                break
    body = body[1:end]
    points: List[Point] = []
    for chunk in body.replace("(", " ").replace(")", ",").split(","):
        parts = chunk.split()
        if len(parts) >= 2:
            try:
                points.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return _dedupe(points)


def _dedupe(points: Sequence[Point]) -> List[Point]:
    out: List[Point] = []
    for point in points:
        if not out or abs(point[0] - out[-1][0]) > 1e-9 or abs(point[1] - out[-1][1]) > 1e-9:
            out.append((float(point[0]), float(point[1])))
    return out


# --- Visum attribute files ---------------------------------------------------


def _node_coordinates(tables: Sequence[visum_att.AttTable]) -> Dict[str, Point]:
    table = visum_att.find_table(tables, "NODE", "NODES", "KNOTEN")
    if table is None:
        return {}
    no_col = _resolve(table.columns, "no")
    x_col = next((c for c in table.columns if _norm(c) in ("XCOORD", "X")), None)
    y_col = next((c for c in table.columns if _norm(c) in ("YCOORD", "Y")), None)
    if not (no_col and x_col and y_col):
        return {}
    nodes: Dict[str, Point] = {}
    for row in table.rows:
        x = visum_att.parse_number(row.get(x_col))
        y = visum_att.parse_number(row.get(y_col))
        if x is None or y is None:
            continue
        nodes[str(row.get(no_col, "")).strip()] = (x, y)
    return nodes


def _link_polylines(
    tables: Sequence[visum_att.AttTable],
) -> Dict[Tuple[str, str, str], List[Point]]:
    """Intermediate polyline vertices from the ``$LINKPOLY`` table."""
    table = visum_att.find_table(tables, "LINKPOLY", "LINKPOLYGON")
    if table is None:
        return {}
    cols = {_norm(c): c for c in table.columns}
    link_col = cols.get("LINKNO") or cols.get("NO")
    from_col = cols.get("FROMNODENO")
    to_col = cols.get("TONODENO")
    index_col = cols.get("INDEX") or cols.get("IDX")
    x_col = cols.get("XCOORD") or cols.get("X")
    y_col = cols.get("YCOORD") or cols.get("Y")
    if not (link_col and from_col and to_col and x_col and y_col):
        return {}
    buckets: Dict[Tuple[str, str, str], List[Tuple[float, Point]]] = {}
    for order, row in enumerate(table.rows):
        x = visum_att.parse_number(row.get(x_col))
        y = visum_att.parse_number(row.get(y_col))
        if x is None or y is None:
            continue
        key = (
            str(row.get(link_col, "")).strip(),
            str(row.get(from_col, "")).strip(),
            str(row.get(to_col, "")).strip(),
        )
        index = visum_att.parse_number(row.get(index_col)) if index_col else None
        buckets.setdefault(key, []).append((float(order) if index is None else index, (x, y)))
    return {
        key: [point for _, point in sorted(items, key=lambda item: item[0])]
        for key, items in buckets.items()
    }


def _rows_to_links(
    rows: Sequence[Dict[str, Any]],
    columns: Sequence[str],
    nodes: Dict[str, Point],
    polylines: Dict[Tuple[str, str, str], List[Point]],
    warnings: List[str],
    wkt_column: Optional[str] = None,
) -> Tuple[List[LinkDirection], str]:
    no_col = _resolve(columns, "no")
    from_col = _resolve(columns, "from_node")
    to_col = _resolve(columns, "to_node")
    if not (no_col and from_col and to_col):
        raise ImportError_(
            "The export must contain the columns NO, FROMNODENO and TONODENO "
            f"(found: {', '.join(columns) or 'nothing'})."
        )
    wkt_col = wkt_column or _resolve(columns, "wkt")
    xf, yf = _resolve(columns, "x_from"), _resolve(columns, "y_from")
    xt, yt = _resolve(columns, "x_to"), _resolve(columns, "y_to")
    name_col = _resolve(columns, "name")
    type_col = _resolve(columns, "type_no")
    length_col = _resolve(columns, "length")
    cap_col = _resolve(columns, "capacity")

    sources: Dict[str, int] = {}
    links: List[LinkDirection] = []
    skipped = 0

    for row in rows:
        link_no = str(row.get(no_col, "")).strip()
        from_node = str(row.get(from_col, "")).strip()
        to_node = str(row.get(to_col, "")).strip()
        if not link_no or not from_node or not to_node:
            skipped += 1
            continue

        geometry: List[Point] = []
        source = ""
        if wkt_col:
            geometry = parse_wkt(str(row.get(wkt_col, "")))
            source = "WKTPOLY"
        if not geometry:
            start = nodes.get(from_node)
            end = nodes.get(to_node)
            middle = polylines.get((link_no, from_node, to_node), [])
            if not middle:
                reverse = polylines.get((link_no, to_node, from_node), [])
                middle = list(reversed(reverse))
            if start and end:
                geometry = _dedupe([start, *middle, end])
                source = "$LINKPOLY" if middle else "$NODE"
        if not geometry and xf and yf and xt and yt:
            x1 = visum_att.parse_number(row.get(xf))
            y1 = visum_att.parse_number(row.get(yf))
            x2 = visum_att.parse_number(row.get(xt))
            y2 = visum_att.parse_number(row.get(yt))
            if None not in (x1, y1, x2, y2):
                geometry = _dedupe([(x1, y1), (x2, y2)])  # type: ignore[arg-type]
                source = "node coordinate columns"
        if len(geometry) < 2:
            skipped += 1
            continue
        sources[source] = sources.get(source, 0) + 1

        attrs = {k: v for k, v in row.items() if k not in (wkt_col,) and v not in (None, "")}
        links.append(
            LinkDirection(
                link_no=link_no,
                from_node=from_node,
                to_node=to_node,
                geometry=geometry,
                name=str(row.get(name_col, "")).strip() if name_col else "",
                type_no=str(row.get(type_col, "")).strip() if type_col else "",
                length=visum_att.parse_number(row.get(length_col)) if length_col else None,
                capacity=visum_att.parse_number(row.get(cap_col)) if cap_col else None,
                attrs=attrs,
            )
        )

    if skipped:
        warnings.append(f"{skipped} rows were skipped because they carry no usable geometry or key.")
    if not links:
        raise ImportError_(
            "No link geometry could be built. Export the links together with WKTPOLY, "
            "or export the whole network so that the $NODE table is included."
        )
    geometry_source = max(sources, key=lambda s: sources[s]) if sources else "unknown"
    return links, geometry_source


def import_att(path: str | os.PathLike[str], encoding: Optional[str] = None) -> ImportResult:
    tables = visum_att.read_file(path, encoding)
    link_table = visum_att.find_table(tables, "LINK", "LINKS", "STRECKE", "STRECKEN")
    if link_table is None:
        available = ", ".join(t.name for t in tables) or "none"
        raise ImportError_(f"No $LINK table found in {os.fspath(path)} (tables: {available}).")
    warnings: List[str] = []
    links, source = _rows_to_links(
        link_table.rows,
        link_table.columns,
        _node_coordinates(tables),
        _link_polylines(tables),
        warnings,
    )
    return ImportResult(links, list(link_table.columns), warnings, source)


def import_csv(path: str | os.PathLike[str], encoding: Optional[str] = None) -> ImportResult:
    import csv

    text = visum_att.read_text(path, encoding)
    # Visum list exports keep the header on the first non comment line.
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("*")]
    if not lines:
        raise ImportError_(f"{os.fspath(path)} is empty.")
    try:
        dialect = csv.Sniffer().sniff(lines[0], delimiters=";,\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"
    reader = csv.DictReader(lines, delimiter=delimiter)
    rows = [{(k or ""): (v or "") for k, v in row.items()} for row in reader]
    columns = list(reader.fieldnames or [])
    warnings: List[str] = []
    links, source = _rows_to_links(rows, columns, {}, {}, warnings)
    return ImportResult(links, columns, warnings, source)


def import_geojson(path: str | os.PathLike[str], encoding: Optional[str] = None) -> ImportResult:
    data = json.loads(visum_att.read_text(path, encoding))
    features = data.get("features") if isinstance(data, dict) else None
    if features is None:
        raise ImportError_(f"{os.fspath(path)} is not a GeoJSON FeatureCollection.")

    rows: List[Dict[str, Any]] = []
    geometries: List[List[Point]] = []
    for feature in features:
        geometry = (feature or {}).get("geometry") or {}
        coords = geometry.get("coordinates") or []
        gtype = (geometry.get("type") or "").lower()
        if gtype == "linestring":
            points = [(float(c[0]), float(c[1])) for c in coords if len(c) >= 2]
        elif gtype == "multilinestring":
            points = [(float(c[0]), float(c[1])) for part in coords for c in part if len(c) >= 2]
        else:
            continue
        points = _dedupe(points)
        if len(points) < 2:
            continue
        rows.append(dict(feature.get("properties") or {}))
        geometries.append(points)

    if not rows:
        raise ImportError_("The GeoJSON file contains no LineString features.")

    columns = list({key: None for row in rows for key in row})
    warnings: List[str] = []
    # Feed the geometry through a synthetic WKT column so that one code path
    # builds every link.
    for row, points in zip(rows, geometries):
        row["__GEOM__"] = "LINESTRING(" + ", ".join(f"{x} {y}" for x, y in points) + ")"
    columns.append("__GEOM__")
    links, _ = _rows_to_links(rows, columns, {}, {}, warnings, wkt_column="__GEOM__")
    return ImportResult(links, [c for c in columns if c != "__GEOM__"], warnings, "GeoJSON")


def import_shapefile(path: str | os.PathLike[str], encoding: Optional[str] = None) -> ImportResult:
    try:
        import shapefile  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError_(
            "Reading shapefiles needs the 'pyshp' package (pip install pyshp), "
            "or export the network as .att / GeoJSON instead."
        ) from exc

    reader = shapefile.Reader(os.fspath(path), encoding=encoding or "cp1250")
    columns = [f[0] for f in reader.fields[1:]]
    rows: List[Dict[str, Any]] = []
    geometries: List[List[Point]] = []
    for record, shape in zip(reader.records(), reader.shapes()):
        points = _dedupe([(float(x), float(y)) for x, y in shape.points])
        if len(points) < 2:
            continue
        rows.append(dict(zip(columns, list(record))))
        geometries.append(points)
    if not rows:
        raise ImportError_("The shapefile contains no polyline features.")
    for row, points in zip(rows, geometries):
        row["__GEOM__"] = "LINESTRING(" + ", ".join(f"{x} {y}" for x, y in points) + ")"
    warnings: List[str] = []
    links, _ = _rows_to_links(rows, columns + ["__GEOM__"], {}, {}, warnings, wkt_column="__GEOM__")
    return ImportResult(links, columns, warnings, "shapefile")


def import_links(path: str | os.PathLike[str], encoding: Optional[str] = None) -> ImportResult:
    """Import any supported export, picking the reader from the file extension."""
    suffix = os.path.splitext(os.fspath(path))[1].lower()
    if suffix in (".att", ".net", ".txt"):
        return import_att(path, encoding)
    if suffix in (".csv", ".tsv"):
        return import_csv(path, encoding)
    if suffix in (".geojson", ".json"):
        return import_geojson(path, encoding)
    if suffix == ".shp":
        return import_shapefile(path, encoding)
    raise ImportError_(
        f"Unknown file type {suffix!r}. Supported: .att, .net, .csv, .geojson, .shp"
    )


def orient_directions(links: Iterable[LinkDirection]) -> List[LinkDirection]:
    """Make every geometry run from its own from-node to its own to-node.

    Visum exports the same polyline for both directions of a link, so the
    reverse direction has to be flipped before the map can offset it to the
    correct side of the carriageway.
    """
    ordered = list(links)
    by_link: Dict[str, List[LinkDirection]] = {}
    for link in ordered:
        by_link.setdefault(link.link_no, []).append(link)

    for group in by_link.values():
        reference = group[0]
        for link in group[1:]:
            if (link.from_node, link.to_node) == (reference.to_node, reference.from_node):
                if _same_start(link.geometry, reference.geometry):
                    link.geometry = list(reversed(link.geometry))
    return ordered


def _same_start(a: Sequence[Point], b: Sequence[Point]) -> bool:
    if not a or not b:
        return False
    return abs(a[0][0] - b[0][0]) < 1e-6 and abs(a[0][1] - b[0][1]) < 1e-6


def read_value_records(
    path: str | os.PathLike[str], encoding: Optional[str] = None
) -> List[Tuple[str, str, str, Dict[str, str]]]:
    """Read counted volumes back from a ``.att`` or ``.csv`` produced by this tool.

    Used to merge the work of several surveyors into one project file.
    """
    suffix = os.path.splitext(os.fspath(path))[1].lower()
    if suffix in (".att", ".net", ".txt"):
        tables = visum_att.read_file(path, encoding)
        table = visum_att.find_table(tables, "LINK", "LINKS")
        if table is None:
            raise ImportError_(f"No $LINK table found in {os.fspath(path)}.")
        columns, rows = list(table.columns), table.rows
    elif suffix in (".csv", ".tsv"):
        import csv

        text = visum_att.read_text(path, encoding)
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("*")]
        delimiter = ";" if lines and lines[0].count(";") >= lines[0].count(",") else ","
        reader = csv.DictReader(lines, delimiter=delimiter)
        columns = list(reader.fieldnames or [])
        rows = [{(k or ""): (v or "") for k, v in row.items()} for row in reader]
    else:
        raise ImportError_(f"Cannot read values from {suffix!r} files; use .att or .csv.")

    no_col = _resolve(columns, "no")
    from_col = _resolve(columns, "from_node")
    to_col = _resolve(columns, "to_node")
    if not (no_col and from_col and to_col):
        raise ImportError_("The file must contain NO, FROMNODENO and TONODENO columns.")

    skip = {no_col, from_col, to_col} | {
        c for c in columns if _norm(c) in ("NAME", "NOTE", "SURVEYOR", "UPDATEDAT")
    }
    value_columns = [c for c in columns if c not in skip]
    records: List[Tuple[str, str, str, Dict[str, str]]] = []
    for row in rows:
        link_no = str(row.get(no_col, "")).strip()
        from_node = str(row.get(from_col, "")).strip()
        to_node = str(row.get(to_col, "")).strip()
        if not (link_no and from_node and to_node):
            continue
        values = {
            c.upper(): str(row.get(c, "")).strip()
            for c in value_columns
            if str(row.get(c, "")).strip() != ""
        }
        if values:
            records.append((link_no, from_node, to_node, values))
    return records
