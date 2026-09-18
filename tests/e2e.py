"""Ověření aplikace v prohlížeči.

Projde TrafficVolumes.html přesně jako uživatel: načte síť, klikne na link,
zapíše oba směry, uloží .att i obrázek a zkontroluje jejich obsah.

    pip install playwright && playwright install chromium
    python3 tests/e2e.py [složka-pro-stažené-soubory]

Proměnná TV_CHROMIUM umožní použít vlastní binárku Chromia.
"""

import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = "file://" + os.path.join(ROOT, "TrafficVolumes.html")
NET = os.path.join(ROOT, "samples", "sample_links.att")
DL = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="tvol-")
LAUNCH = {"args": ["--no-sandbox"]}
if os.environ.get("TV_CHROMIUM"):
    LAUNCH["executable_path"] = os.environ["TV_CHROMIUM"]

errs, fails = [], []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name
          + ((" :: " + str(detail)) if detail and not ok else ""))
    if not ok:
        fails.append(name)

with sync_playwright() as pw:
    b = pw.chromium.launch(**LAUNCH)
    ctx = b.new_context(viewport={"width":1300,"height":820}, accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append("pageerror: "+str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)

    print("\n== načtení ==")
    page.goto(APP); page.wait_for_timeout(300)
    check("úvodní drop zóna", page.is_visible("#drop"))
    page.set_input_files("#file", NET)
    page.wait_for_function("() => !!window.net", timeout=15000); page.wait_for_timeout(400)
    info = page.evaluate("() => ({n: net.links.length, crs: net.crs, sub: document.getElementById('subtitle').textContent})")
    check("55 směrů", info["n"]==55, info)
    check("rozpoznán S-JTSK 5514", "5514" in info["crs"], info["crs"])

    print("\n== obousměrné zadání ==")
    # find a two-way link
    t = page.evaluate("""() => { const c=document.getElementById('map'), r=c.getBoundingClientRect();
        for (let y=40;y<r.height-40;y+=4) for (let x=40;x<r.width-40;x+=4) {
            const h=pick(x,y); if (h) { const p=pairOf(h.key); if (p.b) return {x:x+r.left,y:y+r.top,a:p.a.key,b:p.b.key}; } }
        return null; }""")
    check("nalezen obousměrný link", t is not None, t)
    page.mouse.click(t["x"], t["y"]); page.wait_for_timeout(250)
    dirs = page.evaluate("""() => Array.from(document.querySelectorAll('#dirs label')).map(l => ({
        caption: l.querySelector('span').textContent, id: l.querySelector('input').id }))""")
    check("dva vstupy pro dva směry", len(dirs)==2, dirs)
    check("popisky se šipkou", "→" in dirs[0]["caption"] and "→" in dirs[1]["caption"], dirs)
    check("id vstupů va/vb", [d["id"] for d in dirs]==["va","vb"], dirs)

    page.fill("#va", "12500"); page.fill("#vb", "9800")
    page.click("#save"); page.wait_for_timeout(250)
    saved = page.evaluate("(k) => ({a: values[k[0]], b: values[k[1]], prog: document.getElementById('progress').textContent})", [t["a"], t["b"]])
    check("oba směry uloženy naráz", saved["a"]==12500 and saved["b"]==9800, saved)
    check("postup 2 z 55", "2 z 55" in saved["prog"], saved["prog"])

    print("\n== Enter ukládá, čárka a mezery projdou ==")
    page.fill("#va", "13 200"); page.press("#va", "Enter"); page.wait_for_timeout(200)
    check("mezera jako oddělovač tisíců", page.evaluate("(k)=>values[k]", t["a"])==13200)
    page.fill("#va", "abc"); page.click("#save"); page.wait_for_timeout(200)
    check("nesmysl odmítnut", "není číslo" in page.text_content("#toast"), page.text_content("#toast"))
    page.fill("#va", "13200")

    print("\n== kliknutí na druhý směr otevře stejný link ==")
    page.evaluate("(k) => selectLink(net.byKey[k])", t["b"]); page.wait_for_timeout(200)
    same = page.evaluate("""() => ({a: document.getElementById('va').value,
                                   b: document.getElementById('vb').value,
                                   focused: document.activeElement.id})""")
    check("formulář se neprohodil", same["a"]=="13200" and same["b"]=="9800", same)
    check("kurzor v klikutém směru", same["focused"]=="vb", same)

    print("\n== jednosměrný link ==")
    one = page.evaluate("""() => { for (const l of net.links) { const p=pairOf(l.key); if (!p.b) return l.key; } return null; }""")
    if one:
        page.evaluate("(k)=>selectLink(net.byKey[k])", one); page.wait_for_timeout(200)
        n = page.evaluate("() => document.querySelectorAll('#dirs label').length")
        check("jen jeden vstup", n==1, n)
        check("označeno jako jednosměrný", "jednosměrn" in page.text_content("#link-sub"), page.text_content("#link-sub"))

    print("\n== export .att ==")
    page.fill("#attr", "VOL_DEN")
    with page.expect_download(timeout=15000) as d:
        page.click("#export-att")
    att_path = os.path.join(DL, "out.att"); d.value.save_as(att_path)
    raw = open(att_path,"rb").read()
    text = raw.decode("ascii")
    check("čisté ASCII", True)
    check("název souboru nese atribut", "VOL_DEN" in d.value.suggested_filename, d.value.suggested_filename)
    check("klíčové sloupce", "$LINK:NO;FROMNODENO;TONODENO;VOL_DEN" in text,
          [l for l in text.splitlines() if l.startswith("$LINK")])
    rows = [l for l in text.splitlines() if l and not l.startswith(("*","$"))]
    check("oba směry jako dva řádky", len(rows)==2, rows)
    check("hodnoty sedí", any(r.endswith(";13200") for r in rows) and any(r.endswith(";9800") for r in rows), rows)
    check("CRLF konce řádků", b"\r\n" in raw)

    print("\n== export PNG ==")
    with page.expect_download(timeout=20000) as d2:
        page.click("#export-png")
    png_path = os.path.join(DL, "out.png"); d2.value.save_as(png_path)
    png = open(png_path,"rb").read()
    check("PNG signatura", png[:8]==b"\x89PNG\r\n\x1a\n")
    check("PNG má obsah", len(png)>20000, len(png))

    print("\n== obnovení po zavření ==")
    page2 = ctx.new_page()
    page2.on("pageerror", lambda e: errs.append("reopen: "+str(e)))
    page2.goto(APP); page2.wait_for_timeout(300)
    page2.set_input_files("#file", NET)
    page2.wait_for_function("() => !!window.net", timeout=15000); page2.wait_for_timeout(500)
    restored = page2.evaluate("() => ({n: Object.keys(values).length, prog: document.getElementById('progress').textContent})")
    check("hodnoty obnoveny z prohlížeče", restored["n"]==2, restored)
    page2.close()

    page.screenshot(path=os.path.join(DL,"simple.png"))
    b.close()
print("\nkonzole:", errs[:5] if errs else "čistá")
print("selhalo:", fails if fails else "nic")
sys.exit(1 if (fails or errs) else 0)
