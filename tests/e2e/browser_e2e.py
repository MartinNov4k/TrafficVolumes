"""End to end check of dist/TrafficVolumes.html in a real browser.

Drives the built single file app from a file:// URL exactly as the surveyor
would: load a network, configure the values, click a link on the canvas, type a
volume, and verify every export plus the autosave and reopen paths.

    pip install playwright && playwright install chromium
    python3 tests/e2e/browser_e2e.py [download-dir]

Set TV_CHROMIUM to use a Chromium binary that Playwright did not install.
"""

import json
import os
import re
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = "file://" + os.path.join(ROOT, "dist", "TrafficVolumes.html")
NET = os.path.join(ROOT, "samples", "sample_links.att")
DL = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="tvol-e2e-")
LAUNCH = {"args": ["--no-sandbox"]}
if os.environ.get("TV_CHROMIUM"):
    LAUNCH["executable_path"] = os.environ["TV_CHROMIUM"]

errors, failures = [], []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (" :: " + str(detail) if detail and not ok else ""))
    if not ok:
        failures.append(name)

with sync_playwright() as pw:
    b = pw.chromium.launch(**LAUNCH)
    ctx = b.new_context(viewport={"width": 1400, "height": 880}, accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" else None)

    print("\n== načtení sítě ==")
    page.goto(APP); page.wait_for_timeout(400)
    check("úvodní obrazovka viditelná", page.is_visible("#dropzone"))
    page.set_input_files("#file-input", NET)
    page.wait_for_selector("#setup:not(.hidden)", timeout=5000)
    summary = page.text_content("#setup-summary")
    check("setup ukazuje počet směrů", "55 směrů" in summary, summary)
    check("rozpoznán EPSG:5514", "5514" in page.text_content("#setup-crs"), page.text_content("#setup-crs"))

    print("\n== nastavení veličin ==")
    page.fill("#setup-name", "Sčítání 2026")
    page.click("#btn-add-field")
    rows = page.query_selector_all("#setup-fields .row")
    check("dvě veličiny", len(rows) == 2, len(rows))
    rows[1].query_selector("[data-role=name]").fill("VOL_TV")
    rows[1].query_selector("[data-role=label]").fill("Nákladní")
    rows[1].query_selector("[data-role=unit]").fill("voz/den")
    page.click("#btn-create")
    page.wait_for_selector("#work:not(.hidden)", timeout=5000)

    info = page.evaluate("""() => ({
        items: TV.ui.state.map.items.length,
        crs: TV.ui.state.project.crs,
        fields: TV.ui.state.project.fields.map(f => f.name),
        inputs: document.querySelectorAll('#value-inputs input').length,
        title: document.title
    })""")
    check("55 směrů v mapě", info["items"] == 55, info)
    check("CRS EPSG:5514", info["crs"] == "EPSG:5514", info["crs"])
    check("dvě pole ve formuláři", info["inputs"] == 2, info["inputs"])
    check("název v titulku", "Sčítání 2026" in info["title"], info["title"])

    print("\n== zadání hodnoty ==")
    page.fill("#surveyor", "Novák")
    target = page.evaluate("""() => {
        const c = document.getElementById('map'), r = c.getBoundingClientRect();
        for (let y = 40; y < r.height - 40; y += 5)
          for (let x = 40; x < r.width - 40; x += 5) {
            const hit = TV.ui.state.map.pick(x, y);
            if (hit) return {x: x + r.left, y: y + r.top, key: hit.key};
          }
        return null; }""")
    check("trefen link v mapě", target is not None, target)
    page.mouse.click(target["x"], target["y"]); page.wait_for_timeout(300)
    check("detail otevřen", page.is_visible("#detail"))
    inputs = page.query_selector_all("#value-inputs input")
    inputs[0].fill("12500"); inputs[1].fill("900")
    page.fill("#note", "ruční sčítání")
    page.click("#value-form button[type=submit]"); page.wait_for_timeout(300)
    after = page.evaluate("""() => ({
        progress: document.getElementById('progress-text').textContent,
        values: TV.ui.state.project.valuesOf(TV.ui.state.selected.key),
        note: TV.ui.state.project.entry(TV.ui.state.selected.key).note,
        surveyor: TV.ui.state.project.entry(TV.ui.state.selected.key).surveyor,
        history: document.querySelectorAll('#history-list li').length,
        reverse: TV.ui.state.project.reverseKey(TV.ui.state.selected.key)
    })""")
    check("hodnoty uloženy", after["values"] == {"VOL_MANUAL": "12500", "VOL_TV": "900"}, after["values"])
    check("poznámka uložena", after["note"] == "ruční sčítání", after["note"])
    check("sčítající zapsán", after["surveyor"] == "Novák", after["surveyor"])
    check("postup 1 z 55", "1 z 55" in after["progress"], after["progress"])
    check("historie má 2 záznamy", after["history"] == 2, after["history"])

    print("\n== validace ==")
    inputs[0].fill("12.5")
    page.click("#value-form button[type=submit]"); page.wait_for_timeout(250)
    check("desetinné číslo odmítnuto u int", "celé číslo" in page.text_content("#toast"),
          page.text_content("#toast"))
    inputs[0].fill("12500")

    print("\n== kopie do opačného směru ==")
    if after["reverse"]:
        page.click("#btn-copy"); page.wait_for_timeout(300)
        rev = page.evaluate("(k) => TV.ui.state.project.valuesOf(k)", after["reverse"])
        check("opačný směr má hodnoty", rev.get("VOL_MANUAL") == "12500", rev)
        check("postup 2 z 55", "2 z 55" in page.text_content("#progress-text"),
              page.text_content("#progress-text"))

    print("\n== exporty ==")
    def grab(button, name):
        with page.expect_download(timeout=10000) as info:
            page.click(button)
        d = info.value
        path = os.path.join(DL, name)
        d.save_as(path)
        return path

    csv_path = grab("#btn-csv", "out.csv")
    csv_text = open(csv_path, encoding="utf-8-sig").read()
    check("CSV hlavička", csv_text.splitlines()[0] ==
          "NO;FROMNODENO;TONODENO;NAME;VOL_MANUAL;VOL_TV;NOTE;SURVEYOR;UPDATED_AT",
          csv_text.splitlines()[0])
    check("CSV má 2 datové řádky", len([l for l in csv_text.strip().splitlines()[1:] if l]) == 2)
    check("CSV nese diakritiku", "ruční sčítání" in csv_text)

    att_path = grab("#btn-att", "out.att")
    att_bytes = open(att_path, "rb").read()
    att_text = att_bytes.decode("ascii")
    check("ATT je čisté ASCII", True)
    check("ATT klíčové sloupce", "$LINK:NO;FROMNODENO;TONODENO;VOL_MANUAL;VOL_TV" in att_text,
          [l for l in att_text.splitlines() if l.startswith("$LINK")])
    check("ATT má hodnotu 12500", ";12500;900" in att_text)
    check("ATT bez diakritiky v hlavičce", "Scitani 2026" in att_text,
          [l for l in att_text.splitlines() if "Project" in l])

    png_path = grab("#btn-png", "out.png")
    png = open(png_path, "rb").read()
    check("PNG signatura", png[:8] == b"\x89PNG\r\n\x1a\n")
    check("PNG má rozumnou velikost", len(png) > 20000, len(png))

    html_path = grab("#btn-save-html", "saved.html")
    saved = open(html_path, encoding="utf-8").read()
    check("HTML obsahuje vložená data", 'id="tv-embedded"' in saved)
    m = re.search(r'id="tv-embedded"[^>]*>(.*?)</script>', saved, re.S)
    payload = json.loads(m.group(1).replace("\\u003c", "<"))
    check("vložený projekt má 55 linků", len(payload["links"]) == 55, len(payload["links"]))
    check("vložený projekt má zápisy", len(payload["entries"]) == 2, len(payload["entries"]))
    check("HTML není nafouklé duplicitou", saved.count('id="tv-embedded"') == 1)

    print("\n== znovuotevření uloženého HTML ==")
    page2 = ctx.new_page()
    page2.on("pageerror", lambda e: errors.append("reopen pageerror: " + str(e)))
    page2.goto("file://" + html_path); page2.wait_for_timeout(700)
    reopened = page2.evaluate("""() => ({
        workVisible: !document.getElementById('work').classList.contains('hidden'),
        startHidden: document.getElementById('start').classList.contains('hidden'),
        items: TV.ui.state.map.items.length,
        progress: document.getElementById('progress-text').textContent,
        name: TV.ui.state.project.name,
        surveyor: document.getElementById('surveyor').value,
        fields: TV.ui.state.project.fields.length
    })""")
    check("otevře se rovnou pracovní obrazovka", reopened["workVisible"] and reopened["startHidden"], reopened)
    check("síť obnovena", reopened["items"] == 55, reopened["items"])
    check("data obnovena", "2 z 55" in reopened["progress"], reopened["progress"])
    check("název obnoven", reopened["name"] == "Sčítání 2026", reopened["name"])
    check("sčítající obnoven", reopened["surveyor"] == "Novák", reopened["surveyor"])
    check("veličiny obnoveny", reopened["fields"] == 2, reopened["fields"])
    page2.close()

    print("\n== autosave v prohlížeči ==")
    page.wait_for_timeout(900)
    page3 = ctx.new_page()
    page3.goto(APP); page3.wait_for_timeout(900)
    recent = page3.evaluate("""() => ({
        visible: !document.getElementById('recent-block').classList.contains('hidden'),
        rows: document.querySelectorAll('#recent .recent-row').length,
        text: document.getElementById('recent').textContent
    })""")
    check("rozpracovaná práce nabídnuta", recent["visible"] and recent["rows"] >= 1, recent)
    check("nabídka uvádí projekt", "Sčítání 2026" in recent["text"], recent["text"])
    page3.click("#recent .recent-row button.primary"); page3.wait_for_timeout(700)
    restored = page3.evaluate("""() => ({
        items: TV.ui.state.map.items.length,
        progress: document.getElementById('progress-text').textContent })""")
    check("obnoveno z prohlížeče", restored["items"] == 55 and "2 z 55" in restored["progress"], restored)
    page3.close()

    print("\n== sloučení hodnot z CSV ==")
    page.click("#btn-clear"); page.wait_for_timeout(250)
    page.set_input_files("#merge-input", csv_path); page.wait_for_timeout(600)
    merged = page.text_content("#progress-text")
    check("CSV zpět načteno", "2 z 55" in merged, merged)

    print("\n== hledání ==")
    page.fill("#search", "Husova"); page.dispatch_event("#search", "change"); page.wait_for_timeout(400)
    filtered = page.evaluate("() => Object.keys(TV.ui.state.map.filterKeys || {}).length")
    check("filtr omezil síť", 0 < filtered < 55, filtered)
    page.fill("#search", ""); page.dispatch_event("#search", "change"); page.wait_for_timeout(300)
    check("filtr zrušen", page.evaluate("() => TV.ui.state.map.filterKeys === null"))

    page.screenshot(path=os.path.join(DL, "app.png"))
    b.close()

print("\nkonzole:", errors[:8] if errors else "čistá")
print("selhalo:", failures if failures else "nic")
sys.exit(1 if (failures or errors) else 0)
