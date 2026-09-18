"""Write the collected volumes back out, above all as a Visum attribute file."""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime
from typing import Any, List, Optional, Sequence, TextIO

from . import visum_att
from .model import ValueField
from .storage import Project

#: Encoding Visum reads without complaining on a Czech Windows installation.
DEFAULT_ENCODING = "cp1250"


def _value_cell(field: ValueField, raw: Optional[str]) -> str:
    if raw is None or raw == "":
        return ""
    if field.value_type == "text":
        return str(raw)
    number = visum_att.parse_number(raw)
    if number is None:
        return ""
    if field.value_type == "int":
        return str(int(round(number)))
    return visum_att.format_number(number)


def att_header_comments(project: Project, fields: Sequence[ValueField]) -> List[str]:
    meta = project.meta()
    stats = project.stats()
    lines = [
        "Traffic volumes entered manually with TrafficVolumes",
        f"Project      : {meta.get('name', '')}",
        f"Source net  : {meta.get('source', '')}",
        f"Exported     : {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"Directions   : {stats.filled} filled of {stats.total}",
        "",
        "Before reading this file, create the user defined attributes on the",
        "link network object (Network objects > Links > right click a column header",
        "> 'User-defined attributes...'), using exactly these IDs and types:",
    ]
    for field in fields:
        kind = {"int": "Integer", "float": "Double", "text": "Text"}[field.value_type]
        unit = f", unit {field.unit}" if field.unit else ""
        lines.append(f"  {field.name:<20} {kind}{unit}  -- {field.label}")
    lines += [
        "",
        "Then use File > Import > Attribute file (or 'Read additive network') and",
        "pick this file. The key columns NO;FROMNODENO;TONODENO address one",
        "direction of each link, so both directions keep their own value.",
    ]
    return lines


def export_att(
    project: Project,
    stream: TextIO,
    *,
    fields: Optional[Sequence[ValueField]] = None,
    include_empty: bool = False,
    separator: str = ";",
) -> int:
    """Write a Visum attribute file with one column per value field."""
    all_fields = project.fields()
    selected = list(fields) if fields else all_fields
    columns = ["NO", "FROMNODENO", "TONODENO"] + [f.name for f in selected]

    source = project.iter_all_directions() if include_empty else project.iter_entered()
    rows = []
    for item in source:
        cells = [item["link_no"], item["from_node"], item["to_node"]]
        cells.extend(_value_cell(f, item["values"].get(f.name)) for f in selected)
        rows.append(cells)

    return visum_att.write_table(
        stream,
        "LINK",
        columns,
        rows,
        separator=separator,
        comments=att_header_comments(project, selected),
    )


def export_att_file(
    project: Project,
    path: str | os.PathLike[str],
    *,
    fields: Optional[Sequence[ValueField]] = None,
    include_empty: bool = False,
    encoding: str = DEFAULT_ENCODING,
) -> int:
    with open(path, "w", encoding=encoding, errors="replace", newline="\r\n") as fh:
        return export_att(project, fh, fields=fields, include_empty=include_empty)


def export_csv(
    project: Project,
    stream: TextIO,
    *,
    include_empty: bool = False,
    delimiter: str = ";",
) -> int:
    """Write a spreadsheet friendly table including notes and audit columns."""
    fields = project.fields()
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
    writer.writerow(
        ["NO", "FROMNODENO", "TONODENO", "NAME"]
        + [f.name for f in fields]
        + ["NOTE", "SURVEYOR", "UPDATED_AT"]
    )
    source = project.iter_all_directions() if include_empty else project.iter_entered()
    count = 0
    for item in source:
        writer.writerow(
            [item["link_no"], item["from_node"], item["to_node"], item.get("name") or ""]
            + [_value_cell(f, item["values"].get(f.name)) for f in fields]
            + [item.get("note") or "", item.get("surveyor") or "", item.get("updated_at") or ""]
        )
        count += 1
    return count


def export_geojson(project: Project, stream: TextIO, *, include_empty: bool = True) -> int:
    """Write the network with its values, handy for QGIS cross checks."""
    if project.meta().get("coord_mode") != "geographic":
        raise ValueError(
            "GeoJSON export needs geographic coordinates; this project uses a local "
            "coordinate system. Re-import it with an explicit --crs."
        )
    links, _ = project.query_links(limit=1_000_000)
    features = []
    for link in links:
        if not include_empty and not any(v for v in link["values"].values()):
            continue
        properties = {
            "NO": link["link_no"],
            "FROMNODENO": link["from_node"],
            "TONODENO": link["to_node"],
            "NAME": link["name"],
            "NOTE": link["note"],
            "STATUS": link["status"],
        }
        properties.update(link["values"])
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": link["geom"]},
                "properties": properties,
            }
        )
    json.dump(
        {"type": "FeatureCollection", "features": features},
        stream,
        ensure_ascii=False,
        indent=1,
    )
    return len(features)


VISUM_SNIPPET = '''"""Create the user attributes and read the counted volumes into Visum.

Run this from Visum's own Python console (Scripts > Run script file...), or from
an external Python with the win32com package installed. It needs a Visum
licence; the surveyor does not need one to collect the data.
"""

import os

try:                      # inside Visum the object already exists
    Visum
except NameError:         # outside Visum, attach to a running instance
    import win32com.client
    Visum = win32com.client.Dispatch("Visum.Visum")

ATT_FILE = r"{att_file}"

# Visum COM ValueType codes: 1 = Int, 2 = Real (Double), 5 = Text.
# Check them against the COM help of your Visum version if a call fails.
ATTRIBUTES = [
{attribute_rows}
]

existing = {{a.AttributeID.upper() for a in Visum.Net.Links.Attributes.GetAll}}
for att_id, label, value_type in ATTRIBUTES:
    if att_id.upper() in existing:
        print("user attribute %s already exists" % att_id)
        continue
    Visum.Net.Links.AddUserDefinedAttribute(att_id, att_id, label, value_type)
    print("created user attribute %s" % att_id)

if not os.path.isfile(ATT_FILE):
    raise SystemExit("attribute file not found: %s" % ATT_FILE)

Visum.LoadAttributeFile(ATT_FILE)
print("read %s" % ATT_FILE)
'''


def visum_snippet(project: Project, att_file: str) -> str:
    """Build a ready to run Visum script that creates the UDAs and reads the file."""
    codes = {"int": 1, "float": 2, "text": 5}
    rows = ",\n".join(
        f'    ("{f.name}", "{f.label}", {codes[f.value_type]})' for f in project.fields()
    )
    return VISUM_SNIPPET.format(att_file=os.path.abspath(att_file), attribute_rows=rows)


def to_string(writer, *args: Any, **kwargs: Any) -> str:
    """Run one of the exporters above and return what it wrote as a string."""
    buffer = io.StringIO()
    writer(*args, buffer, **kwargs)
    return buffer.getvalue()
