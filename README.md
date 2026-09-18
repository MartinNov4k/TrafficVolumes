# TrafficVolumes

Ruční zadávání intenzit dopravy na linky z **PTV Visum** — v mapě, po směrech,
**bez licence Visum**. Výsledek se vrací zpět do Visum jako uživatelský atribut
na linku.

Typický scénář: vy máte licenci Visum a exportujete síť. Kolega, projektant nebo
sčítač licenci nemá — dostane jeden projektový soubor a spouštěcí skript, v
prohlížeči proklikává jednotlivé směry a zapisuje intenzity. Vy si pak hotová
data načtete zpět do Visum.

![Náhled](docs/screenshot.png)

## Co to umí

- Načte export linků z Visum: `.att`, `.net`, `.csv`, `.geojson` i `.shp`.
- Vykreslí **každý směr linku zvlášť**, odsazený vpravo ve směru jízdy, se
  šipkou — obousměrný link jsou tedy dvě samostatně klikatelné čáry.
- Po kliknutí se zadá intenzita (i více veličin naráz, např. celkem / nákladní /
  špičková hodina), poznámka a případně příznak „k prověření“.
- Vše se průběžně ukládá do jednoho souboru `*.tvol` včetně historie změn.
- Export zpět do Visum jako `.att` s klíčem `NO;FROMNODENO;TONODENO`, takže
  každý směr dostane svou hodnotu. Navíc CSV, GeoJSON a pomocný skript pro Visum.
- Práce více lidí se slučuje příkazem `merge`.

## Požadavky

**Jen Python 3.9 nebo novější.** Žádné knihovny se neinstalují — mapa,
souřadnicové transformace i webový server jsou napsané nad standardní knihovnou,
takže to běží i na uzamčeném firemním počítači bez přístupu k internetu.

Volitelně:

- `pyproj` — pokud potřebujete jiný souřadnicový systém než S-JTSK, WGS84 nebo
  Web Mercator (`pip install pyproj`),
- `pyshp` — pro čtení shapefilů (`pip install pyshp`).

## Postup

### 1. Export sítě z Visum

Nejjednodušší je **uložit síť jako `.net`** (`File > Export > Network file`,
resp. „Uložit síť jako…“). Soubor obsahuje tabulky `$NODE`, `$LINK` a
`$LINKPOLY`, ze kterých se geometrie sestaví sama a nemusíte nic vybírat.

Druhá možnost je export seznamu linků do `.att`: otevřete seznam linků
(`Lists > Network > Links`), nechte v něm zobrazené alespoň sloupce

```
NO   FROMNODENO   TONODENO   WKTPOLY
```

a přidejte, co se má sčítajícímu zobrazovat jako kontext (`NAME`, `TYPENO`,
`NUMLANES`, `CAPPRT`, `V0PRT`…). Seznam pak uložte tlačítkem pro uložení
seznamu jako soubor atributů (`*.att`).

> `WKTPOLY` je atribut linku s geometrií ve formátu WKT. Když ho nemáte,
> stačí místo něj `FromNode\XCoord`, `FromNode\YCoord`, `ToNode\XCoord`,
> `ToNode\YCoord` — linky se pak vykreslí jako úsečky.

### 2. Vytvoření projektu

```bash
python -m trafficvolumes create sit.att -o scitani2026.tvol --name "Sčítání 2026"
```

Souřadnicový systém se rozpozná automaticky (S-JTSK/Krovák EPSG:5514 i 5513,
WGS84, Web Mercator). Když chcete mít jistotu, zadejte ho:

```bash
python -m trafficvolumes create sit.att -o scitani2026.tvol --crs epsg:5514
```

Více zadávaných veličin definujete opakovaným `--field` ve tvaru
`NÁZEV[:typ[:popisek[:jednotka]]]`, kde typ je `int`, `float` nebo `text`.
Název se stane ID uživatelského atributu ve Visum:

```bash
python -m trafficvolumes create sit.att -o scitani2026.tvol \
  --field "VOL_DEN:int:Intenzita celkem:voz/den" \
  --field "VOL_TV:int:Z toho nákladní:voz/den" \
  --field "VOL_SH:int:Špičková hodina:voz/h"
```

### 3. Zadávání intenzit (bez licence Visum)

Sčítajícímu pošlete složku `trafficvolumes/`, soubor `*.tvol` a
`start_windows.bat` (na Linuxu/macOS `start_linux_mac.sh`). Po dvojkliku se
otevře prohlížeč s mapou. Ručně je to:

```bash
python -m trafficvolumes serve scitani2026.tvol --open
```

V mapě se táhnutím posouvá, kolečkem přibližuje, kliknutím se vybere směr
linku. Vlevo se zadá hodnota a uloží klávesou <kbd>Enter</kbd>. Klávesa
<kbd>N</kbd> skočí na nejbližší nevyplněný směr, <kbd>O</kbd> přepne na opačný
směr, tlačítko „Kopírovat →opačný“ zapíše stejné hodnoty i do protisměru.
Ukládá se okamžitě do `*.tvol`, nic se nemůže ztratit zavřením okna.

Podkladová mapa je standardně vypnutá, aby aplikace fungovala offline. Když je
internet k dispozici, zapněte ji přepínačem a spusťte server s `--basemap osm`.

Pro práci po síti (více lidí na jeden projekt):

```bash
python -m trafficvolumes serve scitani2026.tvol --host 0.0.0.0
```

Server v tom případě vypíše přístupový token, který je součástí odkazu.

### 4. Export zpět pro Visum

```bash
python -m trafficvolumes export scitani2026.tvol -o intenzity
```

Vznikne `intenzity.att` (jen vyplněné směry) a `intenzity_read_into_visum.py`.
Volitelně `--csv` a `--geojson`; `--include-empty` zapíše i prázdné směry
(pozor, Visum jimi přepíše stávající hodnoty prázdnou hodnotou).

### 5. Načtení do Visum

1. Ve Visum vytvořte na objektu **Link** uživatelské atributy — v seznamu linků
   pravým tlačítkem na záhlaví sloupce → *User-defined attributes…*, případně
   přes nabídku uživatelských atributů sítě. Použijte **přesně** ID a typy
   vypsané v hlavičce souboru `.att` (např. `VOL_DEN`, typ *Integer*).
2. Načtěte soubor atributů (`File > Import > Attribute file…`; v některých
   verzích *„Read attribute file“* přímo ze seznamu linků).

Klíčové sloupce `NO;FROMNODENO;TONODENO` adresují jeden konkrétní směr linku,
takže každý směr si ponese svou hodnotu.

Krok 1 i 2 umí udělat i vygenerovaný skript `intenzity_read_into_visum.py`,
spuštěný z Python konzole ve Visum (`Scripts > Run script file…`).

## Více sčítajících

Každý dostane kopii projektu, pracuje na své části a pošle soubor zpět.
Sloučení:

```bash
python -m trafficvolumes merge scitani2026.tvol od_novaka.tvol od_svobodove.tvol
```

Slučovat lze i z `.att` nebo `.csv`. Přepínač `--keep` ponechá hodnoty, které
už v projektu jsou, místo jejich přepsání.

## Přehled příkazů

| Příkaz | K čemu |
| --- | --- |
| `create` | vytvoří projekt z exportu Visum |
| `serve` | spustí mapu v prohlížeči |
| `export` | zapíše `.att` / CSV / GeoJSON pro Visum |
| `info` | vypíše, co projekt obsahuje a kolik je hotovo |
| `merge` | sloučí hodnoty z jiných projektů nebo souborů |
| `fields` | zobrazí nebo změní zadávané veličiny |

Nápovědu k jednotlivým příkazům vypíše `python -m trafficvolumes <příkaz> --help`.

## Když něco nesedí

**„No link geometry could be built“** — export neobsahuje geometrii. Přidejte do
seznamu sloupec `WKTPOLY`, nebo exportujte celou síť jako `.net`, aby byla
součástí tabulka `$NODE`.

**Síť se v mapě zobrazuje na špatném místě** — špatně odhadnutý souřadnicový
systém. Vytvořte projekt znovu s výslovným `--crs epsg:5514` (nebo `5513`).
Když souřadnicový systém není podporovaný, `--crs local` zobrazí síť v rovinném
plátně bez podkladové mapy; zadávání funguje stejně.

**Diakritika v `.att` je rozsypaná** — Visum na českých Windows čte cp1250, což
je výchozí kódování exportu. Pokud potřebujete jiné, použijte
`--encoding utf-8`.

**Intenzity se po načtení do Visum neobjeví** — zkontrolujte, že se ID
uživatelského atributu přesně shoduje s názvem sloupce v `.att` a že je atribut
založený na objektu *Link*, ne na uzlu nebo úseku.

## Ukázková data

`samples/sample_links.att` je malá vzorová síť v S-JTSK (EPSG:5514), na které si
lze celý postup vyzkoušet:

```bash
python -m trafficvolumes create samples/sample_links.att -o ukazka.tvol --force
python -m trafficvolumes serve ukazka.tvol --open
```

## Testy

```bash
python -m unittest discover -s tests -v
```

## Licence

MIT.
