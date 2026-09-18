"""TrafficVolumes - manual traffic count entry for PTV Visum link networks.

The package lets a Visum user export links, hand the resulting project file to a
colleague who has no Visum licence, collect manually entered traffic volumes per
link direction in a browser based map, and read the values back into Visum as a
user defined attribute.

Only the Python standard library is required.  ``pyproj`` and ``pyshp`` are used
when they happen to be installed, but nothing depends on them.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
