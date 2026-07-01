# najdi.py — vyhledávač počasí ze stanic ČHMÚ

Jednoduchý program do příkazové řádky, který se ptá na **otevřená data Českého
hydrometeorologického ústavu** a odpoví na otázky typu:

- *Kdy na téhle stanici naposledy pršelo a jak dlouho?*
- *Kdy bylo naposledy 35 °C a víc — a kolikrát za poslední dobu?*
- *Kdy naposledy foukalo přes 15 m/s nebo ležel sníh?*
- *Jaký kód má stanice v mém městě?*

Umí hledat **déšť, teplotu, mráz, vítr, vlhkost, sluneční svit i sníh** a pracuje
s **desetiminutovými** i **denními** měřeními z archivu ČHMÚ, který sahá zhruba
**13 měsíců do minulosti**.

---

## Co je potřeba

- **Python 3.8 nebo novější**
- Knihovna **requests**:

  ```
  pip install requests
  ```

- Připojení k internetu (program si data stahuje za běhu).

---

## Jak to funguje v kostce

Vše se ovládá jedním příkazem `najdi.py` a dvojicí hlavních voleb:

- `--co` — **co** hledáš (`stanice`, nebo počasí: `dest`, `teplota`, `mraz`, `vitr`, `vlhko`, `slunce`, `snih`)
- `--kde` — **kde** hledáš (název města u stanic, nebo kód stanice u počasí)

Volitelně `--zdroj` přepíná mezi `10min` (výchozí) a `denni` daty (viz [sekci 5](#5-denní-data---zdroj)).

Postup je vždy stejný:

1. Najdeš si **kód stanice** podle města (`--co stanice`).
2. S tímto kódem se ptáš na **počasí** (`--co dest` nebo `--co teplota`).

---

## 1. Najít stanici

```
python najdi.py --co stanice --kde "Brno"
```

Vypíše všechny stanice, jejichž název obsahuje zadaný text:

```
Nalezené stanice pro „Brno“ (4):

┌─────────────────────┬──────────────────┬──────────────────────┬───────┬──────┐
│ WSI kód (--kde)     │ Stanice          │ Zeměpisná poloha     │ Výška │ Od   │
├─────────────────────┼──────────────────┼──────────────────────┼───────┼──────┤
│ 0-203-0-41501153002 │ Brno, Jundrov    │ 49.2019, 16.5608     │ 260 m │ 1925 │
│ 0-20000-0-11723     │ Brno, Tuřany     │ 49.153056, 16.688889 │ 241 m │ 1948 │
│ 0-203-0-11721       │ Brno, Žabovřesky │ 49.2165, 16.5677     │ 236 m │ 1973 │
│ 0-203-0-41502109601 │ Brno, Židenice   │ 49.1983, 16.631111   │ 200 m │ 1998 │
└─────────────────────┴──────────────────┴──────────────────────┴───────┴──────┘
```

První sloupec (**WSI kód**) je přesně to, co pak vložíš do `--kde` při hledání
počasí.

> ### ⚠️ Důležité: hledá se podle názvu, ne podle polohy
>
> Stanice se vyhledávají **fulltextem** — tedy podle **názvu** (případně kódu),
> **ne geolokačně**. Program tedy **nenajde nejbližší stanici k zadanému místu**.
> Když napíšeš `--kde "Brno"`, dostaneš stanice, které mají v názvu „Brno", nikoli
> stanici nejblíž nějaké adrese.
>
> Hodí se to, když přibližně víš, že ve městě nějaká stanice je, a chceš zjistit
> její kód. Když ti vyhledávání nic nevrátí, zkus blízké větší město nebo jinou
> část názvu (např. `"Žabovřesky"`). Na diakritice ani velikosti písmen nezáleží
> (`zabovresky` najde `Žabovřesky`).

---

## 2. Najít déšť

Poslední déšť na stanici:

```
python najdi.py --co dest --kde 0-203-0-11721
```

```
Stanice 0-203-0-11721 — úhrn srážek > 0 mm  (místní čas)

┌───┬──────────────────────────┬────────┬────────┐
│ # │ Období                   │  Délka │   Úhrn │
├───┼──────────────────────────┼────────┼────────┤
│ 1 │ 16.06.2026 19:50 – 20:00 │ 10 min │ 0.1 mm │
└───┴──────────────────────────┴────────┴────────┘
```

Program najde poslední **souvislou srážkovou epizodu**, zjistí, jak dlouho
trvala a kolik celkem spadlo.

Více posledních dešťů (např. posledních 5) pomocí `--hloubka`:

```
python najdi.py --co dest --kde 0-203-0-11721 --hloubka 5
```

Jen vydatnější déšť? Nastav práh úhrnu na jeden desetiminutový interval pomocí
`--kolik`:

```
python najdi.py --co dest --kde 0-203-0-11721 --kolik ">=1"
```

---

## 3. Najít teplotu

U teploty je práh **povinný** — musíš říct, co tě zajímá. Třeba poslední epizody,
kdy bylo 35 °C a víc:

```
python najdi.py --co teplota --kde 0-20000-0-11723 --kolik ">=35" --hloubka 5
```

```
Stanice 0-20000-0-11723 — teplota >= 35 °C  (místní čas)

┌───┬──────────────────────────┬────────────┬──────────────┐
│ # │ Období                   │      Délka │ Max. teplota │
├───┼──────────────────────────┼────────────┼──────────────┤
│ 1 │ 29.06.2026 11:10 – 17:20 │ 6 h 10 min │      37.7 °C │
│ 2 │ 28.06.2026 11:20 – 19:40 │ 8 h 20 min │        38 °C │
└───┴──────────────────────────┴────────────┴──────────────┘
```

Funguje i na chladno — třeba kdy naposledy mrzlo:

```
python najdi.py --co teplota --kde 0-20000-0-11723 --kolik "<0"
```

---

## 4. Další jevy

Stejná logika (poslední souvislé epizody) funguje i pro vítr, vlhkost, sluneční
svit a přízemní mráz. Liší se jen tím, co `--co` říká a co se vypíše jako souhrn:

| `--co` | Co hledá | `--kolik` | Souhrn epizody |
|--------|----------|-----------|----------------|
| `dest` | Srážky (mm za 10 min) | volitelné (výchozí > 0) | celkový úhrn |
| `teplota` | Teplota vzduchu (°C) | **povinné** | nejvyšší teplota |
| `mraz` | Přízemní teplota při zemi (°C) | volitelné (výchozí < 0) | nejnižší teplota |
| `vitr` | Nárazy větru (m/s) | **povinné** | nejsilnější náraz |
| `vlhko` | Relativní vlhkost (%) | **povinné** | nejvyšší vlhkost |
| `slunce` | Sluneční svit | volitelné (výchozí > 0) | svit celkem |
| `snih` | Výška sněhu (cm, jen `--zdroj denni`) | volitelné (výchozí > 0) | největší výška |

Příklady:

```
python najdi.py --co vitr   --kde 0-203-0-11721 --kolik ">=15" --hloubka 3
python najdi.py --co vlhko  --kde 0-203-0-11721 --kolik ">=90"
python najdi.py --co slunce --kde 0-203-0-11721
python najdi.py --co mraz   --kde 0-203-0-11721 --do 28.02.2026
```

```
Stanice 0-203-0-11721 — náraz větru >= 15 m/s  (místní čas)

┌───┬──────────────────────────┬────────┬────────────┐
│ # │ Období                   │  Délka │ Max. náraz │
├───┼──────────────────────────┼────────┼────────────┤
│ 1 │ 29.06.2026 17:10 – 17:20 │ 10 min │   17.2 m/s │
│ 2 │ 31.05.2026 17:20 – 17:30 │ 10 min │     15 m/s │
│ 3 │ 11.05.2026 14:00 – 14:10 │ 10 min │   15.1 m/s │
└───┴──────────────────────────┴────────┴────────────┘
```

---

## 5. Denní data (`--zdroj`)

Ve výchozím stavu se čtou **desetiminutová** měření. Přepínačem `--zdroj denni`
přejdeš na **denní** data, kde:

- **epizoda = po sobě jdoucí dny** (ne minuty), takže snadno najdeš třeba
  vlnu veder nebo souvislé deštivé období,
- jsou navíc jevy, které v 10min datech nejsou — hlavně **`snih`** (výška
  sněhové pokrývky),
- vyhledávání je rychlejší, protože jeden soubor pokrývá celý měsíc.

```
python najdi.py --co teplota --kde 0-203-0-11721 --zdroj denni --kolik ">=30" --hloubka 3
```

```
Stanice 0-203-0-11721 — denní maximum teploty >= 30 °C  (místní čas)

┌───┬─────────────────────────┬────────┬──────────────┐
│ # │ Období                  │  Délka │ Max. teplota │
├───┼─────────────────────────┼────────┼──────────────┤
│ 1 │ 18.06.2026 – 29.06.2026 │ 12 dní │      38.9 °C │
│ 2 │ 26.05.2026 – 27.05.2026 │  2 dny │      31.3 °C │
│ 3 │ 24.05.2026              │  1 den │      30.1 °C │
└───┴─────────────────────────┴────────┴──────────────┘
```

Sníh (jen v denním zdroji):

```
python najdi.py --co snih --kde 0-203-0-11721 --zdroj denni --do 28.02.2026
```

Dostupnost jevů se mezi zdroji liší: `vlhko` je jen v 10min, `snih` jen
v denním; `dest`, `teplota`, `mraz`, `vitr`, `slunce` jsou v obou (v denním
počítají s denními agregáty — `teplota` je denní maximum, `slunce` je v
hodinách). Když zadáš jev, který ve zvoleném zdroji není, program ti rovnou
vypíše, co je dostupné.

---

## Přehled voleb

| Volba | Zkratka | Význam |
|-------|---------|--------|
| `--co` | `-c` | Co hledat: `stanice`, nebo počasí (`dest`, `teplota`, `mraz`, `vitr`, `vlhko`, `slunce`, `snih`). **Povinné.** |
| `--kde` | | Město/název u stanic, nebo WSI kód stanice u počasí. **Povinné.** |
| `--zdroj` | `-z` | Zdroj dat: `10min` (výchozí) nebo `denni`. Viz sekci 5. |
| `--kolik` | `-k` | Práh hodnoty s operátorem, např. `">=35"`, `"<0"`, `">=1"`. U teploty **povinné**, u deště volitelné (výchozí: jakýkoli úhrn > 0). |
| `--hloubka` | `-d` | Kolik posledních epizod vypsat (výchozí 1). |
| `--maximalni_prodleva` | `-m` | Kolik minut přestávky se ještě počítá do jedné epizody (výchozí 0 = jakékoli přerušení epizodu ukončí). |
| `--od` | | Hledat jen od tohoto data (např. `13.06.2026`). |
| `--do` | | Hledat jen do tohoto data (např. `16.06.2026`). |

Nápovědu zobrazíš kdykoli:

```
python najdi.py -h
```

### Operátory pro `--kolik`

Hodnotu vždy uveď v uvozovkách (kvůli znakům `<` a `>`):

`>=` , `>` , `<=` , `<` , `==` (nebo `=`). Příklady: `">=35"`, `">5"`, `"<0"`,
`"==0"`. Bez operátoru se předpokládá `>=` (tedy `"35"` znamená `">=35"`).

### Co je „epizoda" a k čemu je `--maximalni_prodleva`

Epizoda je **souvislé období**, kdy podmínka platila. Měření chodí po 10 minutách.
Ve výchozím stavu (`--maximalni_prodleva 0`) jakýkoli výpadek epizodu ukončí.
Když povolíš třeba `--maximalni_prodleva 30`, krátké přestávky do 30 minut se
berou jako součást téže epizody (dva blízké dešťíky se spojí v jeden).

U denního zdroje (`--zdroj denni`) je krok jeden den a epizoda jsou po sobě
jdoucí dny; `--maximalni_prodleva` (v minutách) tam tak prakticky nemá smysl —
ve výchozím stavu epizodu ukončí každý den, kdy podmínka neplatila.

### Omezení rozsahu pomocí `--od` a `--do`

Když tě zajímá jen konkrétní období, ohranič ho. Program pak nestahuje a
neprochází celý archiv, takže je rychlejší:

```
python najdi.py --co dest --kde 0-203-0-11721 --od 13.06.2026 --do 16.06.2026 --hloubka 10
```

Volby jdou použít i samostatně — `--do` bez `--od` hledá nejnovější epizodu
do daného data, `--od` bez `--do` zase od daného data po současnost. Datum lze
psát jako `13.06.2026` i `2026-06-13`, hranice se berou v místním čase (`--od`
od půlnoci, `--do` do konce dne).

### Kešování dat (proměnná `CACHE`)

Aby opakované hledání nestahovalo stále stejné soubory, program si stažená data
ukládá na disk. Chování řídí proměnná `CACHE` úplně na začátku souboru
`najdi.py`:

```python
CACHE = True   # výchozí stav: kešování zapnuté
```

Jak to funguje:

- Stažené soubory se ukládají do složky **`cache/<kód-stanice>/`** vedle skriptu
  (vytvoří se sama). Při dalším hledání se stejný soubor načte z disku, místo
  aby se stahoval znovu — je to **rychlejší** a u už stažených dat to funguje
  i **bez internetu**.
- Kešují se **jen neměnná data** — uzavřené měsíce a dny **před dneškem**.
  Aktuální (dnešní, resp. probíhající měsíc) soubor se **nikdy nekešuje** a vždy
  se stáhne čerstvý, takže nikdy nedostaneš zastaralá dnešní data.
- **Vypnutí:** nastav `CACHE = False`. Program pak nic neukládá ani nečte
  z disku a vše stahuje vždy znovu.
- **Vyprázdnění:** smaž složku `cache/` (klidně celou, vytvoří se zase).

Složka `cache/` je jen lokální a do gitu se necommituje (je v `.gitignore`).

---

## Dobré vědět

- **Časy** jsou ve výpisu v **místním čase** (podle nastavení tvého počítače).
- **Historie** sahá zhruba 13 měsíců zpět. Když hledáš hlouběji, než kam data
  sahají, program vypíše jen to, co našel.
- Při prvním hledání stanice si program stáhne jejich seznam do souboru
  `stanice.json` a příště už ho čte **bez internetu**. Pro aktualizaci seznamu
  tento soubor smaž.
- **Stažená data se kešují** na disk, aby opakované hledání bylo rychlé — viz
  sekci [Kešování dat (proměnná `CACHE`)](#kešování-dat-proměnná-cache).
- Během stahování běží na prvním řádku ukazatel průběhu, který se po dokončení
  nahradí `OK`.

---

## Zdroj dat

Data pocházejí z portálu otevřených dat ČHMÚ
(<https://opendata.chmi.cz>). Jde o neoficiální nástroj, který tato data jen
stahuje a zpracovává.
