# TrafficVolumes

Jednostránková HTML aplikace pro ruční zadávání intenzit dopravy na linky
z **PTV Visum**. Uživatel nepotřebuje licenci Visum, Python ani nic
nainstalovaného — stačí prohlížeč.

![Aplikace](docs/screenshot.png)

## Dvě varianty

| soubor | k čemu |
| --- | --- |
| **[`TrafficVolumes.html`](TrafficVolumes.html)** | pracujete sám: otevřete, přetáhnete síť, zadáte, uložíte `.att` a obrázek |
| **[`TrafficVolumesPredani.html`](TrafficVolumesPredani.html)** | zadáváte přes kolegu: síť se **zapeče přímo do HTML** a předává se jeden soubor tam i zpátky |

Obě se otevírají dvojklikem, fungují offline i z flash disku a nic neodesílají.
Ovládají se stejně; předávací varianta má navíc tlačítko **Uložit HTML**.

## Spuštění

Stáhněte příslušný soubor a otevřete dvojklikem. To je celé.

## Použití

1. **Přetáhněte do okna export linků z Visumu** — `.att`, `.net`, `.csv`
   nebo `.geojson`. Pustit ho můžete kamkoli na stránku, i později, když
   chcete načíst jinou síť.
2. **Klikněte na link v mapě.** V panelu se objeví oba směry
   (`19 → 20` a `20 → 19`) a u každého **dvě políčka**: *všechna vozidla*
   a *vozidla nad 3,5 t*. <kbd>Enter</kbd> uloží všechna najednou.

   Každý směr má svou barvu — **modrou** a **fialovou**. Směr, do kterého
   právě píšete, se v mapě vykreslí celý svou barvou, se svítícím lemem
   a s bílou šipkou ukazující, kudy jede; zbytek sítě zešedne. Nemůže tedy
   dojít k záměně, který směr se edituje.
3. **Uložit .att** stáhne soubor pro Visum, **Uložit obrázek** kartogram v PNG.

Do políček *Atribut ve Visumu* zadejte, jak se mají oba sloupce jmenovat
(výchozí `VOL_ALL` a `VOL_HGV`).

Síť se podkládá mapou **Esri**, zapne se sama. Vyžaduje připojení
k internetu; když se dlaždice nenačtou, aplikace to napíše a pracuje se dál nad
tmavým pozadím. U sítí v neznámém souřadnicovém systému se nezapne, protože
dlaždice by neseděly.

> Proč zrovna Esri a ne OpenStreetMap: stránka otevřená z disku (`file://`)
> neposílá hlavičku `Referer` a JavaScript ji doplnit nesmí. Servery
> OpenStreetMap takové požadavky podle svých
> [pravidel](https://operations.osmfoundation.org/policies/tiles/) odmítají a
> místo mapy pošlou dlaždici s nápisem *Access blocked*. Obejít se to z
> aplikace nedá. (Ve Folium tentýž problém nenastane, protože se mapa obvykle
> otevírá přes `http://localhost`, kde `Referer` existuje.)
>
> Chcete-li jiný zdroj, přepište v `TrafficVolumes.html` konstantu `TILE_URL`
> na libovolnou XYZ adresu; je hned na začátku skriptu.

Uložený obrázek obsahuje podkladovou mapu jen tehdy, když server dlaždic pošle
hlavičky CORS. Bez nich prohlížeč odmítne plátno přečíst, obrázek se uloží bez
podkladu a aplikace to napíše. Aplikace se na to zeptá jednou předem, ne
u každé dlaždice.

## Předání kolegovi

S `TrafficVolumesPredani.html` vypadá kolečko takhle:

1. **U vás:** otevřete soubor, přetáhněte do něj export sítě z Visumu,
   zkontrolujte názvy atributů a klikněte **Uložit HTML pro kolegu**.
   Vznikne jeden soubor se zapečenou sítí — u sítě s 450 směry má kolem 130 kB,
   tedy míň než ten `.att`, který byste jinak posílal.
2. **U kolegy:** dvojklik, a rovnou zadává. Žádné přetahování, síť už je uvnitř
   a jiná se do souboru nedostane. Až skončí, klikne **Uložit práci (HTML)**
   a pošle jeden soubor zpět.
3. **U vás:** vrácený soubor otevřete dvojklikem, uvidíte jeho čísla a uděláte
   si z nich **`.att`** i **obrázek**. Názvy atributů pro Visum tak držíte vy,
   kolega je nemá jak rozbít.

Rozdělanou práci lze vracet a posílat opakovaně — soubor se otevře přesně tam,
kde se skončilo.

> **Pozor na poštu.** Firemní e‑mail často blokuje přílohy `.html`. Vyzkoušejte
> to dřív, než na to spolehnete; obvykle pomůže zip nebo sdílení přes
> Teams/OneDrive.
>
> **Zavřením okna přijdete o nezapsané hodnoty** — v obou variantách. Ukládejte
> průběžně.

## Načtení do Visumu

Stažený `.att` vypadá takto:

```
$LINK:NO;FROMNODENO;TONODENO;VOL_ALL;VOL_HGV
1;10;11;12500;900
1;11;10;9800;700
```

Prázdná buňka znamená, že se ta hodnota nesčítala.

Klíčové sloupce `NO;FROMNODENO;TONODENO` adresují **jeden konkrétní směr**
linku, takže každý směr si nese svou hodnotu. Ve Visumu:

1. Vytvořte na objektu **Link** oba uživatelské atributy se stejnými názvy
   (`VOL_ALL` a `VOL_HGV`, typ *Integer*) — v seznamu linků pravým tlačítkem
   na záhlaví sloupce → *User-defined attributes…*
2. Načtěte soubor atributů (`File > Import > Attribute file…`; v některých
   verzích *„Read attribute file“* přímo ze seznamu linků).

Soubor je čisté ASCII s konci řádků CRLF, takže na něm kódování cp1250
nemá co zkazit.

## Co exportovat z Visumu

Nejjednodušší je **uložit síť jako `.net`** — obsahuje tabulky `$NODE`,
`$LINK` a `$LINKPOLY`, ze kterých se geometrie sestaví sama.

Druhá možnost je seznam linků (`Lists > Network > Links`) uložený jako `.att`,
který obsahuje alespoň:

```
NO   FROMNODENO   TONODENO   WKTPOLY
```

Místo `WKTPOLY` postačí i `FromNode\XCoord`, `FromNode\YCoord`,
`ToNode\XCoord`, `ToNode\YCoord` — linky se pak vykreslí jako úsečky.

### Jak se poznají oba směry

Visum exportuje linky třemi způsoby a aplikace si poradí se všemi:

1. **Protisměr ve stejném řádku.** Seznam linků s atributy relace *ReverseLink*
   má vedle `FROMNODENO`/`TONODENO` i `R_FROMNODENO`, `R_TONODENO`,
   `R_TSYSSET`… Druhý směr se vezme odtud. Rozpozná se prefix `R_`, `REV_`,
   `REVERSE_` i `REVERSELINK\`.
2. **Každý směr jako vlastní řádek** (prohozené `FROMNODENO`/`TONODENO`).
   Bere se tak, jak je.
3. **Jeden řádek na link, bez informace o protisměru.** Druhý směr se doplní
   s obrácenou geometrií a v hlavičce je napsáno *oba směry doplněny k N linkům*.

**Jednosměrky** se poznají podle `TSYSSET`: prázdná množina dopravních systémů
znamená, že je směr uzavřený, a takový směr se nenabízí. Když jsou uzavřené
oba směry, export o skutečném provozu nic neříká a link zůstane obousměrný,
aby z mapy nezmizel.

Totéž platí pro GeoJSON i CSV — rozhodují názvy sloupců, ne formát souboru.

## Souřadnicové systémy

Rozpoznají se samy: **S‑JTSK / Krovák** (EPSG:5514 i 5513) a **WGS84**
(včetně souřadnic se třetím rozměrem, který se ignoruje).
Krovák je spočítaný přímo v aplikaci včetně transformace datumu
Bessel → WGS84 (ověřeno proti příkladu z EPSG Guidance Note 7‑2 a proti PROJ).
Neznámý systém se zobrazí v rovinném plátně — zadávání funguje stejně.

## Mapa

Každý směr je samostatná čára odsazená **vpravo ve směru jízdy**, se šipkou.
Vyplněné směry jsou **zelené**, nevyplněné šedé; velikost intenzity ukazuje
šířka čáry a hlavně číslo vypsané vedle ní ve tvaru `12 500 / 900` — všechna
vozidla a z toho vozidla nad 3,5 t.
Táhnutím se posouvá, kolečkem přibližuje, <kbd>Esc</kbd> zruší výběr.

Obrázek uložený tlačítkem obsahuje i podkladovou mapu, pokud je zapnutá
a pokud to server dlaždic dovolí (viz výše).

## Test

```bash
pip install playwright && playwright install chromium
python3 tests/e2e.py      # celá aplikace
python3 tests/tiles.py    # podkladová mapa proti lokálnímu serveru
python3 tests/predani.py  # předávací varianta: zapečení, zadání, vrácení
```

`e2e.py` projde aplikaci v prohlížeči jako uživatel: načtení sítě ve všech
podporovaných podobách, zadání obou směrů, zvýraznění editovaného směru,
validaci čísel, jednosměrné linky, obsah `.att` i PNG.

`tiles.py` si spustí vlastní dlaždicový server, takže nepotřebuje internet,
a ověří chování s hlavičkami CORS, bez nich i při nedostupném serveru.

`predani.py` projde celý kolotoč předání včetně opakovaného uložení.

> Obě HTML varianty jsou samostatné soubory se společným kódem. Změna, která
> se týká obou, se musí udělat dvakrát — kdyby to začalo vadit, dají se sloučit
> do jednoho souboru, který se chová podle toho, jestli v sobě data má.

## Licence

MIT.
