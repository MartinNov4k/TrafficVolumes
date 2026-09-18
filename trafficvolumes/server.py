"""A small HTTP server exposing the project file to the browser based map.

The server only needs the Python standard library, binds to localhost by
default and keeps all state in the project file, so the surveyor just double
clicks a start script and works in their browser.
"""

from __future__ import annotations

import gzip
import json
import mimetypes
import os
import posixpath
import secrets
import traceback
import unicodedata
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from . import exporters
from .storage import MAX_FEATURES, Project, StorageError

WEB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
_GZIP_THRESHOLD = 64 * 1024


def content_disposition(filename: str) -> str:
    """Build a Content-Disposition header that survives a non-ASCII project name.

    HTTP header values are latin-1, so the Czech project names have to travel in
    the RFC 5987 form while a plain ASCII fallback keeps older clients happy.
    """
    ascii_name = (
        unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    )
    ascii_name = "".join(ch for ch in ascii_name if ch.isalnum() or ch in "._-")
    if not any(ch.isalnum() for ch in ascii_name.rsplit(".", 1)[0]):
        ascii_name = "export" + ascii_name[ascii_name.rfind(".") :] if "." in ascii_name else "export"
    quoted = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "TrafficVolumes"
    protocol_version = "HTTP/1.1"

    # -- plumbing -------------------------------------------------------------

    @property
    def project(self) -> Project:
        return self.server.project  # type: ignore[attr-defined]

    @property
    def token(self) -> str:
        return self.server.token  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover - noise
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str = "application/json; charset=utf-8",
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        headers = dict(extra_headers or {})
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
        if accepts_gzip and len(body) > _GZIP_THRESHOLD:
            body = gzip.compress(body, compresslevel=5)
            headers["Content-Encoding"] = "gzip"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in headers.items():
            # Header values are latin-1 on the wire; never let a stray character
            # abort the response half way through.
            self.send_header(key, str(value).encode("latin-1", "replace").decode("latin-1"))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 4 * 1024 * 1024:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body is too large.")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "The request body must be a JSON object.")
        return data

    def _check_token(self, query: Dict[str, List[str]]) -> None:
        if not self.token:
            return
        supplied = self.headers.get("X-Auth-Token") or (query.get("t") or [""])[0]
        if not secrets.compare_digest(supplied, self.token):
            raise ApiError(HTTPStatus.FORBIDDEN, "Missing or wrong access token.")

    # -- dispatch -------------------------------------------------------------

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_HEAD(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                self._check_token(query)
                self._api(method, path, query)
            elif method == "GET":
                self._static(path)
            else:
                raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, f"{method} is not allowed here.")
        except ApiError as exc:
            self._send_json({"error": exc.message}, exc.status)
        except (StorageError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except BrokenPipeError:  # pragma: no cover - client navigated away
            pass
        except Exception:  # pragma: no cover - unexpected, keep the server alive
            traceback.print_exc()
            self._send_json({"error": "Internal server error."}, HTTPStatus.INTERNAL_SERVER_ERROR)

    # -- static files ---------------------------------------------------------

    def _static(self, path: str) -> None:
        if path in ("/", "/index.html"):
            relative = "index.html"
        else:
            relative = posixpath.normpath(path).lstrip("/")
        target = os.path.normpath(os.path.join(WEB_ROOT, relative))
        if not target.startswith(WEB_ROOT + os.sep) or not os.path.isfile(target):
            raise ApiError(HTTPStatus.NOT_FOUND, "Not found.")
        with open(target, "rb") as fh:
            body = fh.read()
        content_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "application/json",
        ):
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, body, content_type)

    # -- API ------------------------------------------------------------------

    def _api(self, method: str, path: str, query: Dict[str, List[str]]) -> None:
        parts = [p for p in path[len("/api/") :].split("/") if p]
        if not parts:
            raise ApiError(HTTPStatus.NOT_FOUND, "Unknown endpoint.")
        head = parts[0]

        if head == "project" and method == "GET":
            return self._send_json(self._project_info())
        if head == "stats" and method == "GET":
            return self._send_json(self.project.stats().to_dict())
        if head == "links" and method == "GET":
            return self._send_json(self._links(query))
        if head == "link" and len(parts) >= 2:
            key = parts[1]
            if len(parts) == 3 and parts[2] == "history" and method == "GET":
                return self._send_json({"history": self.project.history(key)})
            if method == "GET":
                link = self.project.get_link(key)
                if link is None:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Unknown link direction.")
                return self._send_json(link)
            if method == "POST":
                return self._send_json(self._save(key))
            if method == "DELETE":
                surveyor = (query.get("surveyor") or [""])[0]
                return self._send_json(self.project.clear_values(key, surveyor=surveyor))
        if head == "export" and len(parts) == 2 and method == "GET":
            return self._export(parts[1], query)
        raise ApiError(HTTPStatus.NOT_FOUND, "Unknown endpoint.")

    def _project_info(self) -> Dict[str, Any]:
        meta = self.project.meta()
        bounds = self.project.bounds()
        return {
            "name": meta.get("name", ""),
            "crs": meta.get("crs", "LOCAL"),
            "coord_mode": meta.get("coord_mode", "local"),
            "source": meta.get("source", ""),
            "created_at": meta.get("created_at", ""),
            "fields": [f.to_dict() for f in self.project.fields()],
            "bounds": bounds,
            "stats": self.project.stats().to_dict(),
            "basemap": getattr(self.server, "basemap", ""),
            "basemap_attribution": getattr(self.server, "basemap_attribution", ""),
            "read_only": getattr(self.server, "read_only", False),
            "max_features": MAX_FEATURES,
        }

    def _links(self, query: Dict[str, List[str]]) -> Dict[str, Any]:
        bbox: Optional[Tuple[float, float, float, float]] = None
        raw_bbox = (query.get("bbox") or [""])[0]
        if raw_bbox:
            try:
                values = [float(v) for v in raw_bbox.split(",")]
            except ValueError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "bbox must be four numbers.") from exc
            if len(values) != 4:
                raise ApiError(HTTPStatus.BAD_REQUEST, "bbox must be minx,miny,maxx,maxy.")
            bbox = (values[0], values[1], values[2], values[3])
        try:
            limit = int((query.get("limit") or [str(MAX_FEATURES)])[0])
        except ValueError:
            limit = MAX_FEATURES
        links, truncated = self.project.query_links(
            bbox=bbox,
            search=(query.get("search") or [""])[0],
            only_empty=(query.get("only_empty") or ["0"])[0] in ("1", "true", "yes"),
            only_flagged=(query.get("only_flagged") or ["0"])[0] in ("1", "true", "yes"),
            limit=limit,
        )
        return {"links": links, "truncated": truncated, "count": len(links)}

    def _save(self, key: str) -> Dict[str, Any]:
        if getattr(self.server, "read_only", False):
            raise ApiError(HTTPStatus.FORBIDDEN, "This server was started read-only.")
        body = self._read_json()
        values = body.get("values")
        if values is None or not isinstance(values, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "'values' must be an object.")
        note = body.get("note")
        status = body.get("status")
        if status is not None and status not in ("empty", "filled", "flagged"):
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Unknown status {status!r}.")
        return self.project.set_values(
            key,
            {str(k).upper(): v for k, v in values.items()},
            surveyor=str(body.get("surveyor") or ""),
            note=None if note is None else str(note),
            status=status,
        )

    def _export(self, kind: str, query: Dict[str, List[str]]) -> None:
        include_empty = (query.get("include_empty") or ["0"])[0] in ("1", "true", "yes")
        name = (self.project.meta().get("name") or "volumes").replace(" ", "_")
        if kind == "att":
            text = exporters.to_string(
                exporters.export_att, self.project, include_empty=include_empty
            )
            body = text.replace("\n", "\r\n").encode(exporters.DEFAULT_ENCODING, "replace")
            filename, content_type = f"{name}.att", "text/plain; charset=windows-1250"
        elif kind == "csv":
            text = exporters.to_string(
                exporters.export_csv, self.project, include_empty=include_empty
            )
            body = ("﻿" + text).encode("utf-8")
            filename, content_type = f"{name}.csv", "text/csv; charset=utf-8"
        elif kind == "geojson":
            text = exporters.to_string(exporters.export_geojson, self.project)
            body = text.encode("utf-8")
            filename, content_type = f"{name}.geojson", "application/geo+json; charset=utf-8"
        elif kind == "visum-script":
            body = exporters.visum_snippet(self.project, f"{name}.att").encode("utf-8")
            filename, content_type = "read_into_visum.py", "text/x-python; charset=utf-8"
        else:
            raise ApiError(HTTPStatus.NOT_FOUND, f"Unknown export format {kind!r}.")
        self._send(
            HTTPStatus.OK, body, content_type, {"Content-Disposition": content_disposition(filename)}
        )


class TrafficVolumesServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: Tuple[str, int],
        project: Project,
        *,
        token: str = "",
        basemap: str = "",
        basemap_attribution: str = "",
        read_only: bool = False,
        verbose: bool = False,
    ) -> None:
        super().__init__(address, Handler)
        self.project = project
        self.token = token
        self.basemap = basemap
        self.basemap_attribution = basemap_attribution
        self.read_only = read_only
        self.verbose = verbose


def serve(
    project: Project,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    token: str = "",
    basemap: str = "",
    basemap_attribution: str = "",
    read_only: bool = False,
    verbose: bool = False,
) -> TrafficVolumesServer:
    """Create (but do not start) the server."""
    return TrafficVolumesServer(
        (host, port),
        project,
        token=token,
        basemap=basemap,
        basemap_attribution=basemap_attribution,
        read_only=read_only,
        verbose=verbose,
    )
