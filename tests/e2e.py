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
ONE_ROW = os.path.join(ROOT, "samples", "sample_links_one_row.att")
REV_COLS = os.path.join(ROOT, "samples", "sample_links_reverse_cols.geojson")
LOCAL = os.path.join(ROOT, "samples", "sample_links_local.att")
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

    print("\n== export s jedním řádkem na link: oba směry se doplní ==")
    page3 = ctx.new_page()
    page3.on("pageerror", lambda e: errs.append("one-row: " + str(e)))
    page3.goto(APP); page3.wait_for_timeout(250)
    page3.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")
    page3.set_input_files("#file", ONE_ROW)
    page3.wait_for_function("() => !!window.net", timeout=15000); page3.wait_for_timeout(400)
    one = page3.evaluate("""() => ({
        n: net.links.length,
        oneWay: net.links.filter(function (l) { return !pairOf(l.key).b; }).length,
        sub: document.getElementById('subtitle').textContent })""")
    check("z 31 linků je 62 směrů", one["n"] == 62, one)
    check("žádný se netváří jako jednosměrný", one["oneWay"] == 0, one)
    check("doplnění je vidět v hlavičce", "oba směry doplněny" in one["sub"], one["sub"])

    # Both directions must be separately clickable, not drawn on top of each other.
    hits = page3.evaluate("""() => { const c = document.getElementById('map');
        const r = c.getBoundingClientRect(); const found = {};
        for (let y = 30; y < r.height - 30; y += 3)
          for (let x = 30; x < r.width - 30; x += 3) {
            const h = pick(x, y); if (h) found[h.key] = true; }
        return Object.keys(found); }""")
    pair = page3.evaluate("""() => { for (const l of net.links) { const p = pairOf(l.key);
        if (p.b) return {a: p.a.key, b: p.b.key}; } return null; }""")
    check("oba směry jsou samostatně klikatelné",
          pair["a"] in hits and pair["b"] in hits, {"pair": pair, "hits": len(hits)})

    page3.evaluate("(k) => selectLink(net.byKey[k])", pair["a"]); page3.wait_for_timeout(200)
    check("panel nabídne dvě políčka",
          page3.evaluate("() => document.querySelectorAll('#dirs input').length") == 2)
    check("a nepíše jednosměrný",
          "jednosměrn" not in page3.text_content("#link-sub"), page3.text_content("#link-sub"))

    page3.fill("#va", "12500"); page3.fill("#vb", "9800")
    page3.click("#save"); page3.wait_for_timeout(250)
    page3.fill("#attr", "VOL_DEN")
    with page3.expect_download(timeout=15000) as d3:
        page3.click("#export-att")
    one_att = os.path.join(DL, "one_row.att"); d3.value.save_as(one_att)
    rows = [l for l in open(one_att, encoding="ascii").read().splitlines()
            if l and not l.startswith(("*", "$"))]
    no, a_from, a_to = pair["a"].split("|")
    check("doplněný směr je v .att", len(rows) == 2
          and ";".join([no, a_from, a_to, "12500"]) in rows
          and ";".join([no, a_to, a_from, "9800"]) in rows, rows)
    page3.close()

    print("\n== per-směrový export se nezdvojuje ==")
    page4 = ctx.new_page()
    page4.on("pageerror", lambda e: errs.append("per-dir: " + str(e)))
    page4.goto(APP); page4.wait_for_timeout(250)
    page4.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")
    page4.set_input_files("#file", NET)
    page4.wait_for_function("() => !!window.net", timeout=15000); page4.wait_for_timeout(400)
    per = page4.evaluate("""() => ({ n: net.links.length,
        oneWay: net.links.filter(function (l) { return !pairOf(l.key).b; }).length,
        sub: document.getElementById('subtitle').textContent })""")
    check("stále 55 směrů", per["n"] == 55, per)
    check("skutečné jednosměrky zůstaly", per["oneWay"] == 7, per)
    check("nic se nedoplňovalo", "doplněny" not in per["sub"], per["sub"])
    page4.close()

    print("\n== protisměr v týchž sloupcích (R_FROMNODENO, R_TSYSSET) ==")
    page5 = ctx.new_page()
    page5.on("pageerror", lambda e: errs.append("rev-cols: " + str(e)))
    page5.goto(APP); page5.wait_for_timeout(250)
    page5.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")
    page5.set_input_files("#file", REV_COLS)
    page5.wait_for_function("() => !!window.net", timeout=15000); page5.wait_for_timeout(400)
    rev = page5.evaluate("""() => ({
        n: net.links.length,
        oneWay: net.links.filter(function (l) { return !pairOf(l.key).b; }).length,
        crs: net.crs,
        sub: document.getElementById('subtitle').textContent,
        link101: Object.keys(net.byKey).filter(function (k) { return k.indexOf('101|') === 0; }),
        link103: Object.keys(net.byKey).filter(function (k) { return k.indexOf('103|') === 0; }),
        link111: Object.keys(net.byKey).filter(function (k) { return k.indexOf('111|') === 0; }) })""")
    # 14 two-way + 2 one-way + 1 closed both ways, which stays two-way on the map
    check("32 směrů ze 17 linků", rev["n"] == 32, rev)
    check("2 jednosměrné podle TSYSSET", rev["oneWay"] == 2, rev)
    check("nic se nedoplňovalo odhadem", "doplněny" not in rev["sub"], rev["sub"])
    check("WGS84 rozpoznáno", "WGS84" in rev["crs"], rev["crs"])
    check("obousměrný link má oba směry", len(rev["link101"]) == 2, rev["link101"])
    check("uzavřený směr se zahodil", len(rev["link103"]) == 1, rev["link103"])
    check("link uzavřený v obou směrech zůstal celý", len(rev["link111"]) == 2, rev["link111"])

    page5.evaluate("() => selectLink(net.byKey[Object.keys(net.byKey).filter("
                   + "function (k) { return k.indexOf('101|') === 0; })[0]])")
    page5.wait_for_timeout(200)
    check("panel nabídne oba směry",
          page5.evaluate("() => document.querySelectorAll('#dirs input').length") == 2)
    page5.close()

    print("\n== je vidět, který směr se edituje ==")
    page6 = ctx.new_page()
    page6.on("pageerror", lambda e: errs.append("highlight: " + str(e)))
    page6.goto(APP); page6.wait_for_timeout(250)
    page6.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")
    page6.set_input_files("#file", NET)
    page6.wait_for_function("() => !!window.net", timeout=15000); page6.wait_for_timeout(400)
    duo = page6.evaluate("""() => { for (const l of net.links) { const p = pairOf(l.key);
        if (p.b) return {a: p.a.key, b: p.b.key}; } return null; }""")
    page6.evaluate("(k) => selectLink(net.byKey[k])", duo["a"]); page6.wait_for_timeout(250)
    hl = page6.evaluate("""() => ({
        focused: focusedKey,
        active: document.activeElement.id,
        dots: Array.from(document.querySelectorAll('#dirs .dot')).map(function (d) {
            return d.style.background; }),
        marked: Array.from(document.querySelectorAll('#dirs label')).map(function (l) {
            return l.classList.contains('focused'); }) })""")
    check("každý směr má svou barvu", len(hl["dots"]) == 2 and hl["dots"][0] != hl["dots"][1], hl)
    check("zvýrazněn je klikutý směr",
          hl["focused"] == duo["a"] and hl["active"] == "va" and hl["marked"] == [True, False], hl)

    page6.focus("#vb"); page6.wait_for_timeout(250)
    hl2 = page6.evaluate("""() => ({ focused: focusedKey,
        marked: Array.from(document.querySelectorAll('#dirs label')).map(function (l) {
            return l.classList.contains('focused'); }) })""")
    check("přechod do druhého políčka přepne zvýraznění",
          hl2["focused"] == duo["b"] and hl2["marked"] == [False, True], hl2)

    page6.evaluate("(k) => selectLink(net.byKey[k])", duo["b"]); page6.wait_for_timeout(250)
    check("klik na druhý směr v mapě zvýrazní jeho políčko",
          page6.evaluate("() => focusedKey") == duo["b"]
          and page6.evaluate("() => document.activeElement.id") == "vb")

    print("\n== podkladová mapa ==")
    check("přepínač je u zeměpisných souřadnic k dispozici",
          not page6.evaluate(
              "() => document.getElementById('basemap-row').classList.contains('hidden')"))
    check("atribuce je zprvu skrytá",
          page6.evaluate("() => document.getElementById('attrib').classList.contains('hidden')"))
    page6.check("#basemap"); page6.wait_for_timeout(2500)
    bm = page6.evaluate("""() => ({ on: basemapOn, tiles: Object.keys(tiles).length,
        hidden: document.getElementById('attrib').classList.contains('hidden'),
        text: document.getElementById('attrib').textContent,
        drawn: net.visible.length })""")
    check("dlaždice se začaly načítat", bm["on"] and bm["tiles"] > 0, bm)
    check("atribuce OpenStreetMap je vidět",
          not bm["hidden"] and "OpenStreetMap" in bm["text"], bm)
    # The sandbox blocks the tile server, which is exactly the offline case.
    check("síť se kreslí i bez dlaždic", bm["drawn"] > 0, bm)

    with page6.expect_download(timeout=25000) as d6:
        page6.click("#export-png")
    bm_png = os.path.join(DL, "basemap.png"); d6.value.save_as(bm_png)
    check("PNG jde uložit i se zapnutou podkladovou mapou",
          open(bm_png, "rb").read()[:8] == b"\x89PNG\r\n\x1a\n")

    page6.uncheck("#basemap"); page6.wait_for_timeout(250)
    check("vypnutí schová atribuci",
          page6.evaluate("() => document.getElementById('attrib').classList.contains('hidden')"))
    page6.close()

    print("\n== místní souřadnice ==")
    page7 = ctx.new_page()
    page7.on("pageerror", lambda e: errs.append("local: " + str(e)))
    page7.goto(APP); page7.wait_for_timeout(250)
    page7.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")
    page7.set_input_files("#file", LOCAL)
    page7.wait_for_function("() => !!window.net", timeout=15000); page7.wait_for_timeout(400)
    loc = page7.evaluate("""() => ({ crs: net.crs, geo: net.geo, n: net.links.length,
        hidden: document.getElementById('basemap-row').classList.contains('hidden'),
        drawn: net.visible.length })""")
    check("neznámý systém zůstane v rovinném plátně",
          not loc["geo"] and "místní" in loc["crs"], loc)
    check("síť se i tak vykreslí", loc["n"] == 55 and loc["drawn"] > 0, loc)
    check("podkladová mapa se u místních souřadnic nenabízí", loc["hidden"], loc)
    page7.close()

    page.screenshot(path=os.path.join(DL, "simple.png"))
    b.close()
print("\nkonzole:", errs[:5] if errs else "čistá")
print("selhalo:", fails if fails else "nic")
sys.exit(1 if (fails or errs) else 0)
