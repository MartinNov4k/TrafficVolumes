"""Reader and writer for PTV Visum attribute files (``*.att``, ``*.net``).

A Visum attribute file is a plain text file made of comment lines starting with
``*``, table headers such as ``$LINK:NO;FROMNODENO;TONODENO`` and the data rows
that follow them.  The same syntax is used by list exports, by additive network
files and by the "read attribute file" dialog, so a single implementation
covers both the import and the export side of this tool.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Sequence

#: Encodings tried in order when no explicit encoding is given.  Visum writes
#: cp1250 on Czech Windows installations and UTF-8 with a BOM on newer ones.
ENCODINGS = ("utf-8-sig", "cp1250", "cp1252", "latin-1")

_SEPARATORS = (";", "\t", ",")
_NUMBER_RE = re.compile(r"^[+-]?(?:\d[\d.,]*|[.,]\d+)(?:[eE][+-]?\d+)?")


class AttError(ValueError):
    pass


@dataclass
class AttTable:
    """One ``$TABLE:COL;COL;...`` block of an attribute file."""

    name: str
    columns: List[str]
    rows: List[Dict[str, str]] = field(default_factory=list)
    separator: str = ";"

    def column_index(self, name: str) -> int:
        upper = [c.upper() for c in self.columns]
        return upper.index(name.upper())

    def has(self, *names: str) -> bool:
        upper = {c.upper() for c in self.columns}
        return all(n.upper() in upper for n in names)


def read_text(path: str | os.PathLike[str], encoding: Optional[str] = None) -> str:
    """Read a text file, guessing the encoding the way Visum writes them."""
    with open(path, "rb") as fh:
        raw = fh.read()
    candidates = (encoding,) if encoding else ENCODINGS
    last: Optional[Exception] = None
    for enc in candidates:
        if enc is None:
            continue
        try:
            return raw.decode(enc)
        except UnicodeDecodeError as exc:
            last = exc
    raise AttError(f"Cannot decode {path!s}: {last}")


def _guess_separator(header: str) -> str:
    body = header.split(":", 1)[1] if ":" in header else header
    counts = {sep: body.count(sep) for sep in _SEPARATORS}
    best = max(counts, key=lambda s: counts[s])
    return best if counts[best] else ";"


def _split(line: str, separator: str) -> List[str]:
    """Split a data row, honouring double quoted fields."""
    if '"' not in line:
        return [cell.strip() for cell in line.split(separator)]
    out: List[str] = []
    cur: List[str] = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            if in_quotes and i + 1 < len(line) and line[i + 1] == '"':
                cur.append('"')
                i += 2
                continue
            in_quotes = not in_quotes
        elif ch == separator and not in_quotes:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur).strip())
    return out


def parse(text: str) -> List[AttTable]:
    """Parse the whole content of an attribute file into tables."""
    tables: List[AttTable] = []
    current: Optional[AttTable] = None
    for raw_line in text.splitlines():
        line = raw_line.strip("﻿").rstrip("\r\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        if stripped.startswith("$"):
            if ":" not in stripped:
                # Bare markers such as "$VISION" carry no columns.
                current = None
                continue
            head, _, cols = stripped.partition(":")
            separator = _guess_separator(stripped)
            names = [c.strip().strip('"') for c in cols.split(separator)]
            current = AttTable(
                name=head[1:].strip().upper(),
                columns=[n for n in names if n],
                separator=separator,
            )
            tables.append(current)
            continue
        if current is None:
            continue
        cells = _split(line, current.separator)
        if len(cells) < len(current.columns):
            cells.extend([""] * (len(current.columns) - len(cells)))
        current.rows.append(dict(zip(current.columns, cells)))
    return tables


def read_file(path: str | os.PathLike[str], encoding: Optional[str] = None) -> List[AttTable]:
    return parse(read_text(path, encoding))


def find_table(tables: Sequence[AttTable], *names: str) -> Optional[AttTable]:
    """Return the first table whose name matches any of ``names``."""
    wanted = {n.upper() for n in names}
    for table in tables:
        if table.name in wanted:
            return table
    return None


def parse_number(value: object) -> Optional[float]:
    """Parse a Visum numeric cell.

    Handles a comma decimal separator, thousands separators and unit suffixes
    such as ``0.532km`` or ``50km/h``.  Returns ``None`` when the cell holds no
    number at all.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace('"', "")
    if not text:
        return None
    match = _NUMBER_RE.match(text)
    if not match:
        return None
    number = match.group(0).rstrip(".,")
    mantissa, exponent = number, ""
    for marker in ("e", "E"):
        if marker in mantissa:
            mantissa, _, exponent = mantissa.partition(marker)
            exponent = marker + exponent
            break
    last_dot, last_comma = mantissa.rfind("."), mantissa.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        # Both separators present: the rightmost one is the decimal separator.
        decimal_at = max(last_dot, last_comma)
        mantissa = (
            mantissa[:decimal_at].replace(".", "").replace(",", "")
            + "."
            + mantissa[decimal_at + 1 :].replace(".", "").replace(",", "")
        )
    else:
        separator = "." if last_dot >= 0 else ("," if last_comma >= 0 else "")
        if separator:
            head, _, tail = mantissa.rpartition(separator)
            # A single separator with exactly three trailing digits is treated as
            # a decimal separator: Visum never groups thousands in exports.
            mantissa = head.replace(separator, "") + "." + tail
    try:
        return float(mantissa + exponent)
    except ValueError:
        return None


def format_number(value: float, decimals: Optional[int] = None) -> str:
    """Format a number the way Visum expects it: dot decimal, no separators."""
    if decimals is not None:
        return f"{value:.{decimals}f}"
    if float(value).is_integer():
        return str(int(value))
    return repr(round(float(value), 6))


def quote(value: object) -> str:
    text = "" if value is None else str(value)
    if any(ch in text for ch in ';\t,"\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def write_table(
    stream: io.TextIOBase,
    table_name: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
    separator: str = ";",
    comments: Sequence[str] = (),
) -> int:
    """Write one ``$TABLE`` block, returning the number of data rows written."""
    stream.write("$VISION\n")
    for comment in comments:
        for part in str(comment).splitlines() or [""]:
            stream.write(f"* {part}\n")
    stream.write("*\n")
    stream.write("$" + table_name.upper() + ":" + separator.join(c.upper() for c in columns) + "\n")
    count = 0
    for row in rows:
        stream.write(separator.join(quote(cell) for cell in row) + "\n")
        count += 1
    return count


def iter_rows(table: AttTable, *columns: str) -> Iterator[List[str]]:
    """Yield selected columns of every row, matched case insensitively."""
    lookup = {c.upper(): c for c in table.columns}
    keys = [lookup.get(name.upper()) for name in columns]
    for row in table.rows:
        yield [("" if key is None else row.get(key, "")) for key in keys]
