"""Core data structures shared by the importers, the storage layer and the API."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]

#: Fields that identify a link direction in every Visum export.
KEY_COLUMNS = ("NO", "FROMNODENO", "TONODENO")


def direction_key(link_no: str, from_node: str, to_node: str) -> str:
    """Stable identifier of one direction of one link."""
    return f"{link_no}|{from_node}|{to_node}"


@dataclass
class LinkDirection:
    """One direction of one Visum link, ready to be shown on the map."""

    link_no: str
    from_node: str
    to_node: str
    geometry: List[Point] = field(default_factory=list)
    name: str = ""
    type_no: str = ""
    length: Optional[float] = None
    capacity: Optional[float] = None
    attrs: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return direction_key(self.link_no, self.from_node, self.to_node)

    @property
    def reverse_key(self) -> str:
        return direction_key(self.link_no, self.to_node, self.from_node)

    def bbox(self) -> Tuple[float, float, float, float]:
        xs = [p[0] for p in self.geometry]
        ys = [p[1] for p in self.geometry]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class ValueField:
    """A value the surveyor is asked to type in for each link direction."""

    name: str
    label: str = ""
    value_type: str = "int"          # int | float | text
    unit: str = ""
    required: bool = False
    position: int = 0

    ATTR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,48}$")

    def __post_init__(self) -> None:
        self.name = self.name.strip().upper()
        if not self.ATTR_NAME_RE.match(self.name):
            raise ValueError(
                f"{self.name!r} is not a valid Visum user attribute name: use letters, "
                "digits and underscore, starting with a letter."
            )
        if self.value_type not in ("int", "float", "text"):
            raise ValueError(f"Unknown value type {self.value_type!r}")
        self.label = self.label or self.name

    def coerce(self, raw: Any) -> Optional[Any]:
        """Validate and normalise a value typed in by the user."""
        if raw is None:
            return None
        text = str(raw).strip()
        if text == "":
            return None
        if self.value_type == "text":
            return text
        text = text.replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            number = float(text)
        except ValueError as exc:
            raise ValueError(f"{self.label}: {raw!r} is not a number") from exc
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{self.label}: {raw!r} is not a finite number")
        if self.value_type == "int":
            if abs(number - round(number)) > 1e-9:
                raise ValueError(f"{self.label}: {raw!r} must be a whole number")
            return int(round(number))
        return number

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "value_type": self.value_type,
            "unit": self.unit,
            "required": bool(self.required),
            "position": self.position,
        }


DEFAULT_FIELDS: Sequence[ValueField] = (
    ValueField(name="VOL_MANUAL", label="Intenzita (voz/den)", value_type="int", unit="voz/den", position=0),
)
