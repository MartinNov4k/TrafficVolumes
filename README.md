# TrafficVolumes

Jednostránková HTML aplikace pro ruční zadávání intenzit dopravy na linky
z **PTV Visum**. Uživatel nepotřebuje licenci Visum, Python ani nic
nainstalovaného — stačí prohlížeč.

![Aplikace](docs/screenshot.png)

## Spuštění

Stáhněte **[`TrafficVolumes.html`](TrafficVolumes.html)** a otevřete dvojklikem.
To je celé. Funguje offline i z flash disku, nic se nikam neodesílá.

## Použití

1. **Přetáhněte do okna export linků z Visumu** — `.att`, `.net`, `.csv`
   nebo `.geojson`.
2. **Klikněte na link v mapě.** V panelu se objeví oba směry
   (`19 → 20` a `20 → 19`) a do každého se zapíše jeho intenzita.
   <kbd>Enter</kbd> uloží.
3. **Uložit .att** stáhne soubor pro Visum, **Uložit obrázek** kartogram v PNG.

Do políčka *Název atributu ve Visumu* zadejte, jak se má sloupec jmenovat
(výchozí `VOL_MANUAL`).

Hodnoty se průběžně ukládají do prohlížeče, takže zavřené okno o práci
nepřipraví — po opětovném načtení stejné sítě se samy vrátí.

## Načtení do Visumu

Stažený `.att` vypadá takto:

```
$LINK:NO;FROMNODENO;TONODENO;VOL_DEN
1;10;11;12500
1;11;10;9800
```

Klíčové sloupce `NO;FROMNODENO;TONODENO` adresují **jeden konkrétní směr**
linku, takže každý směr si nese svou hodnotu. Ve Visumu:

1. Vytvořte na objektu **Link** uživatelský atribut se stejným názvem
   (`VOL_DEN`, typ *Integer*) — v seznamu linků pravým tlačítkem na záhlaví
   sloupce → *User-defined attributes…*
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

### Jeden řádek na link vs. na směr

Seznam linků se z Visumu často exportuje **s jedním řádkem na link**, ne na
směr. V takovém případě aplikace druhý směr sama doplní (s obrácenou
geometrií) a v hlavičce to napíše — *oba směry doplněny k 31 linkům*. Kliknout
a zapsat tedy jde oba.

Když export **obsahuje oba směry jako samostatné řádky** (mají prohozené
`FROMNODENO`/`TONODENO`), bere se tak, jak je: nic se nedoplňuje a link
uvedený jen jednou je skutečně jednosměrný.

## Souřadnicové systémy

Rozpoznají se samy: **S‑JTSK / Krovák** (EPSG:5514 i 5513) a **WGS84**.
Krovák je spočítaný přímo v aplikaci včetně transformace datumu
Bessel → WGS84 (ověřeno proti příkladu z EPSG Guidance Note 7‑2 a proti PROJ).
Neznámý systém se zobrazí v rovinném plátně — zadávání funguje stejně.

## Mapa

Každý směr je samostatná čára odsazená **vpravo ve směru jízdy**, se šipkou.
Šířka a barva odpovídají zadané intenzitě, nevyplněné směry jsou šedé.
Táhnutím se posouvá, kolečkem přibližuje, <kbd>Esc</kbd> zruší výběr.

## Test

```bash
pip install playwright && playwright install chromium
python3 tests/e2e.py
```

Projde aplikaci v prohlížeči jako uživatel: načtení sítě, zadání obou směrů,
validace, jednosměrné linky, obsah `.att` i PNG, obnovení po zavření.

## Licence

MIT.
