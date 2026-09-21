"""Ověření předávacího kolotoče v TrafficVolumes.html.

Projde celý kolotoč, jak probíhá v praxi: zadavatel načte síť z Visumu a uloží
soubor pro kolegu, kolega ho otevře a rovnou zadává (síť už v něm je a jiná se
do něj nedostane), uloží práci, a zadavatel z vráceného souboru vyrobí .att
i obrázek.

    pip install playwright && playwright install chromium
    python3 tests/predani.py [složka-pro-stažené-soubory]

Proměnná TV_CHROMIUM umožní použít vlastní binárku Chromia.
"""

import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = "file://" + os.path.join(ROOT, "TrafficVolumes.html")
NET = os.path.join(ROOT, "samples", "sample_links.att")
DL = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="tvol-predani-")
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

    print("\n== 1. prázdný soubor: načtení sítě a zapečení ==")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append("p1: "+str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type=="error" and "Failed to load resource" not in m.text else None)
    page.goto(APP); page.wait_for_timeout(300)
    check("drop zóna je vidět", page.is_visible("#drop"))
    check("zatím nic zapečeno", page.evaluate("() => embedded") is False)
    page.set_input_files("#file", NET)
    page.wait_for_function("() => !!window.net", timeout=15000); page.wait_for_timeout(400)
    check("síť načtena", page.evaluate("() => net.links.length")==55)
    check("tlačítko nabízí předání",
          "pro kolegu" in page.text_content("#save-html"), page.text_content("#save-html"))
    page.fill("#attr", "VOL_DEN"); page.fill("#attr-hgv", "VOL_TV")
    with page.expect_download(timeout=20000) as d:
        page.click("#save-html")
    zadani = os.path.join(DL, "zadani.html"); d.value.save_as(zadani)
    check("název souboru říká, že je k zadání",
          "_zadani" in d.value.suggested_filename, d.value.suggested_filename)
    size = os.path.getsize(zadani)
    check("soubor má rozumnou velikost", 60000 < size < 400000, size)
    page.close()

    print("\n== 2. kolega otevře a rovnou zadává ==")
    page2 = ctx.new_page()
    page2.on("pageerror", lambda e: errs.append("p2: "+str(e)))
    page2.on("console", lambda m: errs.append(m.text) if m.type=="error" and "Failed to load resource" not in m.text else None)
    page2.goto("file://"+zadani); page2.wait_for_timeout(700)
    st = page2.evaluate("""() => ({emb: embedded, n: net ? net.links.length : 0,
        dropHidden: document.getElementById('drop').classList.contains('hidden'),
        attr: document.getElementById('attr').value,
        attrHgv: document.getElementById('attr-hgv').value,
        prog: document.getElementById('progress').textContent,
        crs: net.crs, btn: document.getElementById('save-html').textContent })""")
    check("síť je uvnitř souboru", st["emb"] and st["n"]==55, st)
    check("drop zóna se vůbec neukáže", st["dropHidden"], st)
    check("názvy atributů se přenesly", st["attr"]=="VOL_DEN" and st["attrHgv"]=="VOL_TV", st)
    check("zatím 0 vyplněno", st["prog"].startswith("0 z"), st["prog"])
    check("souřadnicový systém se přenesl", "5514" in st["crs"], st["crs"])

    # puštění dalšího souboru nesmí nic přepsat ani odnavigovat
    navs = []
    page2.on("framenavigated", lambda f: navs.append(f.url))
    prevented = page2.evaluate("""() => { const dt = new DataTransfer();
        dt.items.add(new File(['x'], 'jina.att', {type:'text/plain'}));
        let p = null;
        ['dragenter','dragover','drop'].forEach(function (t) {
            const ev = new DragEvent(t, {bubbles:true, cancelable:true, dataTransfer:dt});
            document.getElementById('map').dispatchEvent(ev);
            if (t === 'drop') p = ev.defaultPrevented; });
        return p; }""")
    page2.wait_for_timeout(600)
    check("puštění jiného souboru je odchycené", prevented is True)
    check("a nic nepřepsalo", page2.evaluate("() => net.links.length")==55 and navs==[], navs)

    # zadání hodnot
    t = page2.evaluate("""() => { for (const l of net.links) { const p = pairOf(l.key);
        if (p.b) { selectLink(p.a); return {a:p.a.key, b:p.b.key}; } } return null; }""")
    page2.wait_for_timeout(300)
    page2.fill("#va-all","12500"); page2.fill("#va-hgv","900")
    page2.fill("#vb-all","9800"); page2.fill("#vb-hgv","700")
    page2.click("#save"); page2.wait_for_timeout(300)
    check("hodnoty zapsány", page2.evaluate("(k)=>values[k]", t["a"])=={"all":12500,"hgv":900})
    check("v souboru s daty se pro kolegu už neukládá",
          "kolegu" not in page2.text_content("#save-html")
          and "Uložit HTML" in page2.text_content("#save-html"),
          page2.text_content("#save-html"))
    with page2.expect_download(timeout=20000) as d2:
        page2.click("#save-html")
    vyplneno = os.path.join(DL, "vyplneno.html"); d2.value.save_as(vyplneno)
    check("název říká, že je vyplněno", "_vyplneno" in d2.value.suggested_filename,
          d2.value.suggested_filename)
    page2.close()

    print("\n== 3. vrácený soubor u zadavatele ==")
    page3 = ctx.new_page()
    page3.on("pageerror", lambda e: errs.append("p3: "+str(e)))
    page3.on("console", lambda m: errs.append(m.text) if m.type=="error" and "Failed to load resource" not in m.text else None)
    page3.goto("file://"+vyplneno); page3.wait_for_timeout(700)
    back = page3.evaluate("""() => ({emb: embedded, n: net.links.length,
        prog: document.getElementById('progress').textContent,
        a: values[Object.keys(values)[0]],
        attr: document.getElementById('attr').value })""")
    check("hodnoty se vrátily", back["prog"].startswith("2 z") and back["n"]==55, back)
    check("obě veličiny jsou tam", back["a"] is not None and "hgv" in back["a"], back)
    check("názvy atributů drží", back["attr"]=="VOL_DEN", back)

    with page3.expect_download(timeout=20000) as d3:
        page3.click("#export-att")
    att = os.path.join(DL, "z_vracene.att"); d3.value.save_as(att)
    text = open(att, encoding="ascii").read()
    rows = [l for l in text.splitlines() if l and not l.startswith(("*","$"))]
    check("z vráceného souboru jde udělat .att",
          "$LINK:NO;FROMNODENO;TONODENO;VOL_DEN;VOL_TV" in text and len(rows)==2, rows)
    with page3.expect_download(timeout=25000) as d4:
        page3.click("#export-png")
    png = os.path.join(DL, "z_vracene.png"); d4.value.save_as(png)
    check("i obrázek", open(png,"rb").read()[:8]==b"\x89PNG\r\n\x1a\n")

    # a ještě jednou dokola, ať je jisté, že se to nekazí opakovaným ukládáním
    with page3.expect_download(timeout=20000) as d5:
        page3.click("#save-html")
    again = os.path.join(DL, "znovu.html"); d5.value.save_as(again)
    page4 = ctx.new_page()
    page4.on("pageerror", lambda e: errs.append("p4: "+str(e)))
    page4.goto("file://"+again); page4.wait_for_timeout(700)
    check("opakované uložení nic nerozbije",
          page4.evaluate("() => net.links.length")==55
          and page4.text_content("#progress").startswith("2 z"))
    check("soubor se nenafukuje",
          abs(os.path.getsize(again) - os.path.getsize(vyplneno)) < 4000,
          (os.path.getsize(vyplneno), os.path.getsize(again)))
    page4.close(); page3.close()
    print("\n== ukládání do vybraného souboru ==")
    # Nativní dialog ovládat nejde, takže mu podstrčíme falešný handle; ověřuje
    # se tím celá cesta kolem něj, ne dialog samotný.
    page5 = ctx.new_page()
    page5.on("pageerror", lambda e: errs.append("p5: " + str(e)))
    page5.goto("file://" + vyplneno); page5.wait_for_timeout(700)
    check("tlačítko Do souboru… je k dispozici",
          not page5.evaluate("() => document.getElementById('pick-file').disabled"))

    page5.evaluate("""() => {
        window.__written = [];
        window.showSaveFilePicker = function () {
            return Promise.resolve({
                name: 'zvoleny.html',
                createWritable: function () {
                    var chunks = [];
                    return Promise.resolve({
                        write: function (d) { chunks.push(d); return Promise.resolve(); },
                        close: function () {
                            window.__written.push(chunks.join(''));
                            return Promise.resolve();
                        }
                    });
                }
            });
        };
    }""")
    page5.click("#pick-file"); page5.wait_for_timeout(400)
    after = page5.evaluate("""() => ({ btn: document.getElementById('save-html').textContent,
        pick: document.getElementById('pick-file').textContent,
        hint: document.getElementById('save-hint').textContent })""")
    check("po volbě se ukládá prostě Uložit", after["btn"].strip() == "Uložit", after)
    check("nápověda pojmenuje soubor", "zvoleny.html" in after["hint"], after["hint"])
    check("tlačítko nabízí změnu souboru", "Jiný" in after["pick"], after["pick"])

    # od téhle chvíle se nesmí nic stahovat
    downloads = []
    page5.on("download", lambda d: downloads.append(d.suggested_filename))
    page5.click("#save-html"); page5.wait_for_timeout(800)
    written = page5.evaluate("() => window.__written")
    check("zapsalo se do souboru, ne do stažených", len(written) == 1 and downloads == [],
          {"zapisu": len(written), "stazeno": downloads})
    check("zápis je celá stránka",
          written[0].startswith("<!DOCTYPE html>") and 'id="tv-data"' in written[0],
          written[0][:60] if written else "")

    # a ten zápis musí jít zase otevřít i s hodnotami
    out = os.path.join(DL, "zapsany.html")
    open(out, "w", encoding="utf-8").write(written[0])
    page6 = ctx.new_page()
    page6.on("pageerror", lambda e: errs.append("p6: " + str(e)))
    page6.goto("file://" + out); page6.wait_for_timeout(700)
    check("zapsaný soubor se otevře i s hodnotami",
          page6.evaluate("() => net.links.length") == 55
          and page6.text_content("#progress").startswith("2 z"),
          page6.text_content("#progress"))
    page6.close()

    # zrušený dialog se odbude tiše
    page5.evaluate("""() => {
        window.showSaveFilePicker = function () {
            var e = new Error('zrušeno'); e.name = 'AbortError';
            return Promise.reject(e);
        };
    }""")
    page5.click("#pick-file"); page5.wait_for_timeout(500)
    check("zrušený dialog nic nehlásí",
          page5.evaluate("() => document.getElementById('toast').classList.contains('hidden')"))
    page5.close()

    print("\n== prohlížeč bez toho API ==")
    page7 = ctx.new_page()
    page7.on("pageerror", lambda e: errs.append("p7: " + str(e)))
    page7.add_init_script("delete window.showSaveFilePicker;")
    page7.goto("file://" + vyplneno); page7.wait_for_timeout(700)
    check("tlačítko je neaktivní",
          page7.evaluate("() => document.getElementById('pick-file').disabled"))
    with page7.expect_download(timeout=20000) as d7:
        page7.click("#save-html")
    check("a ukládání se vrátí ke stahování", d7.value.suggested_filename.endswith(".html"),
          d7.value.suggested_filename)
    page7.close()

    b.close()

print("\nkonzole:", errs[:5] if errs else "čistá")
print("selhalo:", fails if fails else "nic")
sys.exit(1 if (fails or errs) else 0)
