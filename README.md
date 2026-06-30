# najdi.py — vyhledávač počasí ze stanic ČHMÚ

Jednoduchý program do příkazové řádky, který se ptá na **otevřená data Českého
hydrometeorologického ústavu** a odpoví na otázky typu:

- *Kdy na téhle stanici naposledy pršelo a jak dlouho?*
- *Kdy bylo naposledy 35 °C a víc — a kolikrát za poslední dobu?*
- *Jaký kód má stanice v mém městě?*

Pracuje s desetiminutovými měřeními z archivu ČHMÚ, který sahá zhruba **13 měsíců
do minulosti**.

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

- `--co` — **co** hledáš (`stanice`, `dest`, `teplota`)
- `--kde` — **kde** hledáš (název města u stanic, nebo kód stanice u počasí)

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
WSI kód (vlož do --kde)  Stanice (poloha; nadm. výška; měří od)
---------------------------------------------------------------
0-203-0-11721            Brno, Žabovřesky  (49.2165, 16.5677; 236 m n.m.; od 1973)
0-20000-0-11723          Brno, Tuřany  (49.153056, 16.688889; 241 m n.m.; od 1948)
...
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
Stanice 0-203-0-11721: úhrn srážek > 0 mm
Naposledy pršelo: 16.06.2026 19:50 – 20:00 (místní čas)
Délka: 10 min
Úhrn: 0.1 mm
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
Stanice 0-20000-0-11723: teplota >= 35 °C — posledních 5 epizod (místní čas):
1. 29.06.2026 11:10 – 17:20  (délka 6 h 10 min, max. teplota 37.7 °C)
2. 28.06.2026 11:20 – 19:40  (délka 8 h 20 min, max. teplota 38 °C)
...
```

Funguje i na chladno — třeba kdy naposledy mrzlo:

```
python najdi.py --co teplota --kde 0-20000-0-11723 --kolik "<0"
```

---

## Přehled voleb

| Volba | Zkratka | Význam |
|-------|---------|--------|
| `--co` | `-c` | Co hledat: `stanice`, `dest`, `teplota`. **Povinné.** |
| `--kde` | | Město/název u stanic, nebo WSI kód stanice u počasí. **Povinné.** |
| `--kolik` | `-k` | Práh hodnoty s operátorem, např. `">=35"`, `"<0"`, `">=1"`. U teploty **povinné**, u deště volitelné (výchozí: jakýkoli úhrn > 0). |
| `--hloubka` | `-d` | Kolik posledních epizod vypsat (výchozí 1). |
| `--maximalni_prodleva` | `-m` | Kolik minut přestávky se ještě počítá do jedné epizody (výchozí 0 = jakékoli přerušení epizodu ukončí). |

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

---

## Dobré vědět

- **Časy** jsou ve výpisu v **místním čase** (podle nastavení tvého počítače).
- **Historie** sahá zhruba 13 měsíců zpět. Když hledáš hlouběji, než kam data
  sahají, program vypíše jen to, co našel.
- Při prvním hledání stanice si program stáhne jejich seznam do souboru
  `stanice.json` a příště už ho čte **bez internetu**. Pro aktualizaci seznamu
  tento soubor smaž.
- Během stahování běží na prvním řádku ukazatel průběhu, který se po dokončení
  nahradí `OK`.

---

## Zdroj dat

Data pocházejí z portálu otevřených dat ČHMÚ
(<https://opendata.chmi.cz>). Jde o neoficiální nástroj, který tato data jen
stahuje a zpracovává.
