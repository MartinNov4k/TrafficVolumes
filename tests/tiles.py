"""Ověření podkladové mapy proti lokálnímu dlaždicovému serveru.

Nepotřebuje internet: spustí si vlastní server ve třech podobách a zkontroluje,
že se dlaždice načtou v obou případech — s hlavičkami CORS i bez nich (tak je
načítá Leaflet a Folium) — a že se obrázek uloží vždy, jen s podkladem nebo bez
něj podle toho, co prohlížeč z plátna dovolí přečíst.

    pip install playwright && playwright install chromium
    python3 tests/tiles.py [složka-pro-stažené-soubory]

Proměnná TV_CHROMIUM umožní použít vlastní binárku Chromia.
"""

import base64
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = "file://" + os.path.join(ROOT, "TrafficVolumes.html")
NET = os.path.join(ROOT, "samples", "sample_links.att")
DL = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="tvol-tiles-")
LAUNCH = {"args": ["--no-sandbox"]}
if os.environ.get("TV_CHROMIUM"):
    LAUNCH["executable_path"] = os.environ["TV_CHROMIUM"]

# Jednobarevná PNG, která zastoupí dlaždici.
TILE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFUlEQVR4nGP8z8Dwn4GBgYEJxgAC"
    "AEYaAwGVeEKMAAAAAElFTkSuQmCC")

fails = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name
          + ((" :: " + str(detail)) if detail and not ok else ""))
    if not ok:
        fails.append(name)


def make_server(with_cors):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(TILE)))
            if with_cors:
                self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(TILE)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(page, port, label, expect_mode, expect_png_basemap):
    page.goto(APP); page.wait_for_timeout(250)
    page.set_input_files("#file", NET)
    page.wait_for_function("() => !!window.net", timeout=15000); page.wait_for_timeout(300)
    page.select_option("#basemap", "custom")
    page.fill("#tileurl", "http://127.0.0.1:" + str(port) + "/{z}/{x}/{y}.png")
    page.dispatch_event("#tileurl", "change")
    page.wait_for_function("() => tilesLoaded > 0", timeout=15000)
    page.wait_for_timeout(600)
    st = page.evaluate("() => ({mode: tileMode, loaded: tilesLoaded, tainted: tilesTainted})")
    print("  ->", label, st)
    check(label + ": režim " + expect_mode, st["mode"] == expect_mode, st)
    check(label + ": dlaždice se vykreslily", st["loaded"] > 0, st)
    check(label + ": plátno " + ("čisté" if expect_png_basemap else "ušpiněné"),
          st["tainted"] != expect_png_basemap, st)

    with page.expect_download(timeout=20000) as d:
        page.click("#export-png")
    path = os.path.join(DL, label.replace(" ", "_") + ".png")
    d.value.save_as(path)
    data = open(path, "rb").read()
    check(label + ": PNG se uložil", data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 10000, len(data))
    msg = page.text_content("#toast")
    check(label + ": zpráva odpovídá",
          ("bez podkladové mapy" in msg) != expect_png_basemap, msg)
    return path

with sync_playwright() as pw:
    b = pw.chromium.launch(**LAUNCH)
    ctx = b.new_context(viewport={"width":1200,"height":760}, accept_downloads=True)

    print("\n== server S hlavičkami CORS ==")
    s1 = make_server(True)
    p1 = ctx.new_page(); errs1 = []
    p1.on("pageerror", lambda e: errs1.append(str(e)))
    a = run(p1, s1.server_address[1], "s CORS", "cors", True)
    check("s CORS: žádné chyby stránky", not errs1, errs1[:3])
    p1.close(); s1.shutdown()

    print("\n== server BEZ hlaviček CORS (jako Leaflet/Folium) ==")
    s2 = make_server(False)
    p2 = ctx.new_page(); errs2 = []
    p2.on("pageerror", lambda e: errs2.append(str(e)))
    bpath = run(p2, s2.server_address[1], "bez CORS", "plain", False)
    check("bez CORS: žádné chyby stránky", not errs2, errs2[:3])
    p2.close(); s2.shutdown()

    print("\n== server nedostupný ==")
    p3 = ctx.new_page()
    p3.goto(APP); p3.wait_for_timeout(250)
    p3.set_input_files("#file", NET)
    p3.wait_for_function("() => !!window.net", timeout=15000); p3.wait_for_timeout(300)
    p3.select_option("#basemap", "custom")
    p3.fill("#tileurl", "http://127.0.0.1:1/{z}/{x}/{y}.png")
    p3.dispatch_event("#tileurl", "change")
    p3.wait_for_timeout(7500)
    st3 = p3.evaluate("() => ({mode: tileMode, loaded: tilesLoaded, links: net.visible.length})")
    check("nedostupný server: síť se kreslí dál", st3["links"] > 0, st3)
    check("nedostupný server: aplikace to oznámí",
          "žádná dlaždice" in p3.text_content("#toast"), p3.text_content("#toast"))
    p3.close()
    b.close()

print("\nselhalo:", fails if fails else "nic")
sys.exit(1 if fails else 0)
