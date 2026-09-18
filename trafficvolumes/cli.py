"""Command line interface: create a project, serve it, export it, merge it."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import webbrowser
from typing import List, Optional, Sequence

from . import __version__, exporters, importers, projection
from .model import DEFAULT_FIELDS, ValueField
from .storage import Project, StorageError

#: Tile servers offered by name so that nobody has to remember a URL template.
BASEMAPS = {
    "osm": (
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> přispěvatelé',
    ),
    "cartodb-light": (
        "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        '© OpenStreetMap přispěvatelé, © <a href="https://carto.com/attributions">CARTO</a>',
    ),
    "cartodb-dark": (
        "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        '© OpenStreetMap přispěvatelé, © <a href="https://carto.com/attributions">CARTO</a>',
    ),
    "none": ("", ""),
}


def parse_field(spec: str, position: int) -> ValueField:
    """Parse ``NAME[:type[:label[:unit]]]`` into a :class:`ValueField`."""
    parts = spec.split(":")
    name = parts[0].strip()
    value_type = (parts[1].strip().lower() if len(parts) > 1 and parts[1].strip() else "int")
    aliases = {"i": "int", "integer": "int", "f": "float", "double": "float",
               "real": "float", "t": "text", "string": "text"}
    value_type = aliases.get(value_type, value_type)
    label = parts[2].strip() if len(parts) > 2 and parts[2].strip() else name
    unit = parts[3].strip() if len(parts) > 3 else ""
    return ValueField(
        name=name, label=label, value_type=value_type, unit=unit, position=position
    )


def _fields_from_args(specs: Optional[Sequence[str]]) -> List[ValueField]:
    if not specs:
        return list(DEFAULT_FIELDS)
    fields = [parse_field(spec, index) for index, spec in enumerate(specs)]
    names = [f.name for f in fields]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise SystemExit(f"Duplicate field name(s): {', '.join(sorted(duplicates))}")
    return fields


# --- commands ----------------------------------------------------------------


def cmd_create(args: argparse.Namespace) -> int:
    print(f"Reading {args.source} ...")
    result = importers.import_links(args.source, args.encoding)
    links = importers.orient_directions(result.links)
    for warning in result.warnings:
        print(f"  warning: {warning}")

    samples = [link.geometry[0] for link in links[:500]]
    crs = args.crs
    if not crs or crs.lower() == "auto":
        crs = projection.detect_crs(samples)
        print(f"  detected coordinate system: {crs}")
    projector = projection.get_projector(crs)
    if projector.mode == "local":
        print(
            "  note: coordinates are kept as they are and the map shows a plain\n"
            "        cartesian view without a background map. Pass --crs EPSG:xxxx\n"
            "        (pyproj installed) to place the network on a real map."
        )
    failed = 0
    for link in links:
        try:
            link.geometry = projector.transform_many(link.geometry)
        except (ValueError, projection.ProjectionError):
            failed += 1
            link.geometry = []
    links = [link for link in links if len(link.geometry) >= 2]
    if failed:
        print(f"  warning: {failed} links dropped, their coordinates could not be transformed.")
    if not links:
        raise SystemExit("No link survived the coordinate transformation; check --crs.")

    fields = _fields_from_args(args.field)
    output = args.output or os.path.splitext(args.source)[0] + ".tvol"
    project = Project.create(
        output,
        links,
        fields=fields,
        name=args.name or os.path.splitext(os.path.basename(args.source))[0],
        crs=projector.crs,
        coord_mode=projector.mode,
        source=os.path.basename(args.source),
        overwrite=args.force,
    )
    stats = project.stats()
    one_way = stats.total - _bidirectional_count(project)
    print(
        f"\nCreated {output}\n"
        f"  link directions : {stats.total}\n"
        f"  one-way links   : {one_way}\n"
        f"  geometry from   : {result.geometry_source}\n"
        f"  value fields    : {', '.join(f.name + ' (' + f.value_type + ')' for f in fields)}\n"
        f"\nHand {os.path.basename(output)} over together with the start script and run:\n"
        f"  python -m trafficvolumes serve {output}"
    )
    return 0


def _bidirectional_count(project: Project) -> int:
    row = project.conn.execute(
        "SELECT COUNT(*) FROM links a WHERE EXISTS ("
        "  SELECT 1 FROM links b WHERE b.link_no = a.link_no "
        "  AND b.from_node = a.to_node AND b.to_node = a.from_node)"
    ).fetchone()
    return int(row[0]) if row else 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    project = Project.open(args.project)
    basemap_url, attribution = BASEMAPS.get(args.basemap, (args.basemap, ""))
    if args.basemap not in BASEMAPS and "{z}" not in args.basemap:
        raise SystemExit(
            f"--basemap must be one of {', '.join(BASEMAPS)} or a XYZ URL template."
        )

    token = args.token or ""
    loopback = args.host in ("127.0.0.1", "localhost", "::1")
    if not loopback and not token and not args.no_token:
        token = secrets.token_urlsafe(12)
        print("The server is reachable from the network, so an access token was generated.")

    httpd = serve(
        project,
        host=args.host,
        port=args.port,
        token=token,
        basemap=basemap_url,
        basemap_attribution=attribution,
        read_only=args.read_only,
        verbose=args.verbose,
    )
    host = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{host}:{httpd.server_address[1]}/" + (f"?t={token}" if token else "")
    stats = project.stats()
    print(f"\nTrafficVolumes {__version__} — {project.meta().get('name', '')}")
    print(f"  {stats.filled} of {stats.total} link directions filled in")
    print(f"  project file : {os.path.abspath(args.project)}")
    print(f"\n  Open in a browser:  {url}\n")
    print("  Press Ctrl+C to stop. Everything is saved into the project file as you type.")

    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    project = Project.open(args.project)
    base = args.output or os.path.splitext(args.project)[0]
    wrote_any = False

    if not args.no_att:
        path = base if base.lower().endswith(".att") else base + ".att"
        count = exporters.export_att_file(
            project, path, include_empty=args.include_empty, encoding=args.encoding
        )
        print(f"{path}: {count} link directions")
        script_path = os.path.splitext(path)[0] + "_read_into_visum.py"
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(exporters.visum_snippet(project, path))
        print(f"{script_path}: helper script that creates the user attributes and reads the file")
        wrote_any = True

    if args.csv:
        path = base if base.lower().endswith(".csv") else base + ".csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            count = exporters.export_csv(project, fh, include_empty=args.include_empty)
        print(f"{path}: {count} rows")
        wrote_any = True

    if args.geojson:
        path = base if base.lower().endswith(".geojson") else base + ".geojson"
        with open(path, "w", encoding="utf-8") as fh:
            count = exporters.export_geojson(project, fh)
        print(f"{path}: {count} features")
        wrote_any = True

    if wrote_any:
        fields = project.fields()
        print("\nIn Visum: create these link user attributes, then read the .att file")
        print("(File > Import > Attribute file):")
        for field in fields:
            kind = {"int": "Integer", "float": "Double", "text": "Text"}[field.value_type]
            print(f"  {field.name:<20} {kind}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    project = Project.open(args.project)
    meta = project.meta()
    stats = project.stats()
    print(f"Project      : {meta.get('name', '')}")
    print(f"File         : {os.path.abspath(args.project)}")
    print(f"Source       : {meta.get('source', '')}")
    print(f"Created      : {meta.get('created_at', '')}")
    print(f"CRS          : {meta.get('crs', '')} ({meta.get('coord_mode', '')})")
    print(f"Directions   : {stats.total}")
    print(f"Filled in    : {stats.filled} ({(100 * stats.filled / stats.total) if stats.total else 0:.1f} %)")
    print(f"Flagged      : {stats.flagged}")
    print("Value fields :")
    for field in project.fields():
        unit = f" [{field.unit}]" if field.unit else ""
        print(f"  {field.name:<20} {field.value_type:<6} {field.label}{unit}")
    bounds = project.bounds()
    if bounds:
        print(f"Extent       : {bounds[0]:.6f}, {bounds[1]:.6f} .. {bounds[2]:.6f}, {bounds[3]:.6f}")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    project = Project.open(args.project)
    total_updated = 0
    total_missing = 0
    for source in args.sources:
        if source.lower().endswith((".tvol", ".sqlite", ".db")):
            other = Project.open(source)
            records = [
                (item["link_no"], item["from_node"], item["to_node"], item["values"])
                for item in other.iter_entered()
            ]
        else:
            records = importers.read_value_records(source, args.encoding)
        updated, missing = project.import_values(
            records, surveyor=args.surveyor or os.path.basename(source), overwrite=not args.keep
        )
        print(f"{source}: {updated} directions updated, {missing} not found in the project")
        total_updated += updated
        total_missing += missing
    stats = project.stats()
    print(f"\n{stats.filled} of {stats.total} directions now carry a value.")
    return 0 if total_updated or not total_missing else 1


def cmd_fields(args: argparse.Namespace) -> int:
    project = Project.open(args.project)
    if not args.field:
        return cmd_info(args)
    fields = _fields_from_args(args.field)
    project.set_fields(fields)
    print("Value fields replaced:")
    for field in fields:
        print(f"  {field.name:<20} {field.value_type:<6} {field.label}")
    print("Values of fields that no longer exist were removed.")
    return 0


# --- argument parsing --------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trafficvolumes",
        description=(
            "Collect traffic volumes for PTV Visum links by hand, on a map, without a "
            "Visum licence, and write them back as a link user attribute."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Typical workflow:\n"
            "  1) in Visum export the links (with WKTPOLY, or the whole network)\n"
            "  2) python -m trafficvolumes create links.att -o sber.tvol\n"
            "  3) send sber.tvol to the surveyor, who runs\n"
            "       python -m trafficvolumes serve sber.tvol --open\n"
            "  4) python -m trafficvolumes export sber.tvol --att intenzity.att\n"
            "  5) in Visum create the user attribute and read intenzity.att\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"TrafficVolumes {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="build a project file from a Visum export")
    create.add_argument("source", help=".att / .net / .csv / .geojson / .shp export of the links")
    create.add_argument("-o", "--output", help="project file to write (default: <source>.tvol)")
    create.add_argument("--name", default="", help="project name shown in the browser")
    create.add_argument(
        "--crs", default="auto",
        help="coordinate system of the export: auto, epsg:5514, epsg:5513, wgs84, local, "
             "or any EPSG code when pyproj is installed",
    )
    create.add_argument(
        "--field", action="append", metavar="NAME[:TYPE[:LABEL[:UNIT]]]",
        help="value to collect, repeatable; TYPE is int, float or text "
             "(default: VOL_MANUAL:int:'Intenzita (voz/den)':voz/den)",
    )
    create.add_argument("--encoding", help="encoding of the export (default: guess)")
    create.add_argument("-f", "--force", action="store_true", help="overwrite an existing project")
    create.set_defaults(func=cmd_create)

    serve_parser = subparsers.add_parser("serve", help="open the map in a browser")
    serve_parser.add_argument("project", help="project file created with 'create'")
    serve_parser.add_argument("-p", "--port", type=int, default=8765)
    serve_parser.add_argument(
        "--host", default="127.0.0.1",
        help="0.0.0.0 makes the map reachable from other machines (a token is then required)",
    )
    serve_parser.add_argument("--token", default="", help="require this access token")
    serve_parser.add_argument(
        "--no-token", action="store_true", help="serve on the network without a token"
    )
    serve_parser.add_argument(
        "--basemap", default="none",
        help="background map: " + ", ".join(BASEMAPS) + ", or an XYZ URL template "
             "(needs internet; the map works without one)",
    )
    serve_parser.add_argument("--open", action="store_true", help="open the browser automatically")
    serve_parser.add_argument("--read-only", action="store_true", help="refuse any change")
    serve_parser.add_argument("-v", "--verbose", action="store_true", help="log every request")
    serve_parser.set_defaults(func=cmd_serve)

    export = subparsers.add_parser("export", help="write the volumes out for Visum")
    export.add_argument("project")
    export.add_argument("-o", "--output", help="output path or base name")
    export.add_argument(
        "--att", action="store_true",
        help="write the Visum attribute file (this is the default, the flag is optional)",
    )
    export.add_argument(
        "--no-att", action="store_true", help="skip the .att file and only write the extras"
    )
    export.add_argument("--csv", action="store_true", help="also write a CSV with notes")
    export.add_argument("--geojson", action="store_true", help="also write GeoJSON for QGIS")
    export.add_argument(
        "--include-empty", action="store_true",
        help="include directions without a value (Visum would overwrite them with blanks)",
    )
    export.add_argument(
        "--encoding", default=exporters.DEFAULT_ENCODING,
        help=f"encoding of the .att file (default: {exporters.DEFAULT_ENCODING})",
    )
    export.set_defaults(func=cmd_export)

    info = subparsers.add_parser("info", help="show what a project file contains")
    info.add_argument("project")
    info.set_defaults(func=cmd_info)

    merge = subparsers.add_parser("merge", help="merge values from other projects or files")
    merge.add_argument("project", help="project to merge into")
    merge.add_argument("sources", nargs="+", help="other .tvol projects, .att or .csv files")
    merge.add_argument("--surveyor", default="", help="name recorded in the change history")
    merge.add_argument(
        "--keep", action="store_true", help="keep values already present instead of overwriting"
    )
    merge.add_argument("--encoding")
    merge.set_defaults(func=cmd_merge)

    fields = subparsers.add_parser("fields", help="show or replace the collected value fields")
    fields.add_argument("project")
    fields.add_argument("--field", action="append", metavar="NAME[:TYPE[:LABEL[:UNIT]]]")
    fields.set_defaults(func=cmd_fields)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (StorageError, importers.ImportError_, projection.ProjectionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc.filename}: file not found", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
