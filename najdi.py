#!/usr/bin/env python3
"""Univerzální vyhledávač posledních epizod meteorologického jevu na zvolené
stanici ČHMÚ.

Veřejné API data-provider.chmi.cz vrací jen posledních ~2 dny, proto čteme
desetiminutová data z otevřeného archivu opendata.chmi.cz. Aktuální (neuzavřený)
měsíc je k dispozici po dnech, starší měsíce jako jeden soubor za měsíc.

Postupujeme časem zpět – nejprve po dnech aktuálním měsícem, pak po měsících
archivem – a hledáme souvislé epizody, kdy zvolený jev splňoval zadanou
podmínku. Epizoda se rozšiřuje do minulosti, dokud podmínka (s tolerancí
přestávek --maximalni_prodleva) trvá.

Nejprve si přes --co stanice najdeš WSI kód stanice podle názvu, ten pak vložíš
do --kde při hledání konkrétního jevu.

Použití:
    python najdi.py --co stanice --kde "Brno"
    python najdi.py --co dest --kde 0-203-0-11721
    python najdi.py --co dest --kde 0-203-0-11721 --kolik ">=1" --hloubka 5
    python najdi.py --co teplota --kde 0-20000-0-11723 --kolik ">=35" --hloubka 10"""

import argparse
import datetime as dt
import itertools
import json
import operator
import os
import re
import sys
import threading
import unicodedata
import requests

# Český překlad systémových hlášek argparse (usage:, options:, nápověda -h, chyby).
_ARGPARSE_CZ = {
    "usage: ": "použití: ",
    "options": "argumenty",
    "optional arguments": "argumenty",
    "positional arguments": "poziční argumenty",
    "show this help message and exit": "zobrazí tuto nápovědu a skončí",
    "show program's version number and exit": "zobrazí verzi programu a skončí",
    "the following arguments are required: %s":
        "chybí povinné argumenty: %s",
    "one of the arguments %s is required":
        "je nutný jeden z argumentů %s",
    "argument %(argument_name)s: %(message)s":
        "argument %(argument_name)s: %(message)s",
    "invalid choice: %(value)r (choose from %(choices)s)":
        "neplatná volba: %(value)r (vyber z %(choices)s)",
    "unrecognized arguments: %s": "neznámé argumenty: %s",
    "expected one argument": "očekávám jeden argument",
    "expected at most one argument": "očekávám nejvýše jeden argument",
    "expected at least one argument": "očekávám alespoň jeden argument",
    "invalid %(type)s value: %(value)r":
        "neplatná hodnota typu %(type)s: %(value)r",
    "ambiguous option: %(option)s could match %(matches)s":
        "nejednoznačná volba: %(option)s může odpovídat %(matches)s",
    "%(prog)s: error: %(message)s\n": "%(prog)s: chyba: %(message)s\n",
}
argparse._ = lambda text: _ARGPARSE_CZ.get(text, text)

BASE_10MIN = "https://opendata.chmi.cz/meteorology/climate/recent/data/10min/"
BASE_DENNI = "https://opendata.chmi.cz/meteorology/climate/recent/data/daily/"
META_DIR = "https://opendata.chmi.cz/meteorology/climate/recent/metadata/"

# Lokální kopie seznamu stanic – při prvním běhu se stáhne, pak se čte offline.
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stanice.json")

# Pojistka, jak hluboko do minulosti smíme jít (archiv drží zhruba 13 měsíců).
MAX_MESICU_ZPET = 24

# Krok měření jednotlivých zdrojů (rozestup sousedních záznamů).
KROK_10MIN = dt.timedelta(minutes=10)
KROK_DENNI = dt.timedelta(days=1)

# Jevy pro 10minutová data: element, jednotka a způsob souhrnu epizody.
JEVY_10MIN = {
    "dest": {
        "element": "SRA10M", "jednotka": "mm", "popis": "úhrn srážek",
        "veta": "Naposledy pršelo:", "souhrn_label": "úhrn", "souhrn_fn": sum,
        "vyzaduje_kolik": False, "vychozi": (operator.gt, ">", 0.0),
    },
    "teplota": {
        "element": "T", "jednotka": "°C", "popis": "teplota",
        "veta": "Naposledy naměřeno:", "souhrn_label": "max. teplota",
        "souhrn_fn": max, "vyzaduje_kolik": True, "vychozi": None,
    },
    "mraz": {
        "element": "TPM", "jednotka": "°C", "popis": "přízemní teplota",
        "veta": "Naposledy mrzlo při zemi:", "souhrn_label": "min. teplota",
        "souhrn_fn": min, "vyzaduje_kolik": False,
        "vychozi": (operator.lt, "<", 0.0),
    },
    "vitr": {
        "element": "Fmax", "jednotka": "m/s", "popis": "náraz větru",
        "veta": "Naposledy foukalo:", "souhrn_label": "max. náraz",
        "souhrn_fn": max, "vyzaduje_kolik": True, "vychozi": None,
    },
    "vlhko": {
        "element": "H", "jednotka": "%", "popis": "vlhkost",
        "veta": "Naposledy naměřeno:", "souhrn_label": "max. vlhkost",
        "souhrn_fn": max, "vyzaduje_kolik": True, "vychozi": None,
    },
    "slunce": {
        "element": "SSV10M", "jednotka": "min", "popis": "sluneční svit",
        "veta": "Naposledy svítilo slunce:", "souhrn_label": "svit celkem",
        "souhrn_fn": lambda vals: round(sum(vals)), "vyzaduje_kolik": False,
        "vychozi": (operator.gt, ">", 0.0),
        # V datech jsou sekundy svitu za 10 min; přepočítáme na minuty.
        "prevod": lambda s: s / 60,
    },
}

# Jevy pro denní data: jiné kódy elementů (denní agregáty), navíc sníh.
# Epizoda zde znamená po sobě jdoucí dny.
JEVY_DENNI = {
    "dest": {
        "element": "SRA", "jednotka": "mm", "popis": "denní úhrn srážek",
        "veta": "Naposledy pršelo:", "souhrn_label": "úhrn", "souhrn_fn": sum,
        "vyzaduje_kolik": False, "vychozi": (operator.gt, ">", 0.0),
    },
    "teplota": {
        "element": "TMA", "jednotka": "°C", "popis": "denní maximum teploty",
        "veta": "Naposledy naměřeno:", "souhrn_label": "max. teplota",
        "souhrn_fn": max, "vyzaduje_kolik": True, "vychozi": None,
    },
    "mraz": {
        "element": "TPM", "jednotka": "°C", "popis": "přízemní teplota",
        "veta": "Naposledy mrzlo při zemi:", "souhrn_label": "min. teplota",
        "souhrn_fn": min, "vyzaduje_kolik": False,
        "vychozi": (operator.lt, "<", 0.0),
    },
    "vitr": {
        "element": "Fmax", "jednotka": "m/s", "popis": "náraz větru",
        "veta": "Naposledy foukalo:", "souhrn_label": "max. náraz",
        "souhrn_fn": max, "vyzaduje_kolik": True, "vychozi": None,
    },
    "slunce": {
        "element": "SSV", "jednotka": "hod", "popis": "sluneční svit",
        "veta": "Naposledy svítilo slunce:", "souhrn_label": "svit celkem",
        "souhrn_fn": sum, "vyzaduje_kolik": False,
        "vychozi": (operator.gt, ">", 0.0),
    },
    "snih": {
        "element": "SCE", "jednotka": "cm", "popis": "výška sněhu",
        "veta": "Naposledy ležel sníh:", "souhrn_label": "max. výška",
        "souhrn_fn": max, "vyzaduje_kolik": False,
        "vychozi": (operator.gt, ">", 0.0),
    },
}

OPERATORY = {
    ">=": operator.ge, "<=": operator.le, "==": operator.eq, "=": operator.eq,
    ">": operator.gt, "<": operator.lt,
}

SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json"})


# ---------- Průběhový indikátor na jednom řádku ----------

class Prubeh:
    """Indikátor průběhu na jednom řádku (přepisuje se přes \\r). Animaci kreslí
    vlákno na pozadí, takže se točí i během blokujícího stahování. Mimo terminál
    (přesměrovaný výstup) se neaktivuje, aby nešpinil data."""

    ZNAKY = "|/-\\"

    def __init__(self, stream=sys.stderr):
        self.stream = stream
        self.aktivni = hasattr(stream, "isatty") and stream.isatty()
        self.zprava = ""
        self._predchozi = 0
        self._stop = threading.Event()
        self._vlakno = None

    def start(self, zprava):
        self.zprava = zprava
        if not self.aktivni:
            return
        self._vlakno = threading.Thread(target=self._bezi, daemon=True)
        self._vlakno.start()

    def uprav(self, zprava):
        self.zprava = zprava

    def _bezi(self):
        for znak in itertools.cycle(self.ZNAKY):
            self._radek(f"{self.zprava} {znak}")
            if self._stop.wait(0.1):
                break

    def _radek(self, text):
        # Doplníme mezerami, aby se přepsal delší předchozí řádek.
        pad = max(0, self._predchozi - len(text))
        self.stream.write("\r" + text + " " * pad)
        self.stream.flush()
        self._predchozi = len(text)

    def hotovo(self, vysledek="OK"):
        self._stop.set()
        if self._vlakno is not None:
            self._vlakno.join()
        if self.aktivni:
            self._radek(f"{self.zprava} {vysledek}")
            self.stream.write("\n")
            self.stream.flush()


# Globální indikátor, který stahovací funkce průběžně informují, co dělají.
PRUBEH = None


def _oznam(zprava):
    if PRUBEH is not None:
        PRUBEH.uprav(zprava)


# ---------- Vyhledávání stanic (--co stanice) ----------

def bez_diakritiky(s):
    """Malá písmena bez diakritiky pro porovnávání nezávislé na háčcích."""
    rozlozene = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in rozlozene if not unicodedata.combining(c)).lower()


def nejnovejsi_meta1():
    """Najde URL nejnovějšího souboru meta1-YYYYMMDD.json v archivu."""
    _oznam("Hledám aktuální seznam stanic")
    html = SESSION.get(META_DIR, timeout=30).text
    data = re.findall(r"meta1-(\d{8})\.json", html)
    if data:
        return META_DIR + f"meta1-{max(data)}.json"
    # Záloha, kdyby výpis adresáře selhal: zkus několik dní zpět.
    den = dt.date.today()
    for _ in range(10):
        url = META_DIR + f"meta1-{den:%Y%m%d}.json"
        if SESSION.head(url, timeout=30).status_code == 200:
            return url
        den -= dt.timedelta(days=1)
    raise RuntimeError("Nepodařilo se najít soubor s metadaty stanic.")


def stahni_stanice():
    """Stáhne seznam stanic z opendata a vrátí ho jako seznam slovníků
    s klíči wsi, kod, nazev, lon, lat, vyska, od."""
    url = nejnovejsi_meta1()
    _oznam("Stahuji seznam stanic")
    payload = SESSION.get(url, timeout=30).json()
    # header: WSI,GH_ID,FULL_NAME,GEOGR1,GEOGR2,ELEVATION,BEGIN_DATE
    stanice = []
    for wsi, kod, nazev, lon, lat, vyska, od in payload["data"]["data"]["values"]:
        stanice.append({"wsi": wsi, "kod": kod, "nazev": nazev,
                        "lon": lon, "lat": lat, "vyska": vyska, "od": od})
    return stanice


def nacti_stanice():
    """Vrátí seznam stanic. Pokud existuje lokální stanice.json, čte se z něj
    (offline). Jinak se data stáhnou a do stanice.json se uloží pro příště."""
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)

    stanice = stahni_stanice()
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(stanice, f, ensure_ascii=False, indent=2)
    return stanice


def hledej_stanice(dotaz):
    """Vrátí stanice, jejichž název, WSI nebo interní kód obsahují dotaz
    (bez ohledu na velikost písmen a diakritiku)."""
    q = bez_diakritiky(dotaz)
    return [s for s in nacti_stanice()
            if q in bez_diakritiky(s["nazev"])
            or q in bez_diakritiky(s["kod"])
            or q in bez_diakritiky(s["wsi"])]


def vypis_stanice(nalezene, dotaz):
    if not nalezene:
        print(f"Žádná stanice neodpovídá dotazu „{dotaz}“.")
        return

    nalezene.sort(key=lambda s: bez_diakritiky(s["nazev"]))
    nadpis = "WSI kód (vlož do --kde)"
    sirka_wsi = max([len(nadpis)] + [len(s["wsi"]) for s in nalezene])
    print(f"{nadpis:<{sirka_wsi}}  Stanice (poloha; nadm. výška; měří od)")
    print("-" * (sirka_wsi + 40))
    for s in nalezene:
        rok = str(s["od"])[:4]
        print(f"{s['wsi']:<{sirka_wsi}}  "
              f"{s['nazev']}  ({s['lat']}, {s['lon']}; {s['vyska']:g} m n.m.; "
              f"od {rok})")
    print(f"\nNalezeno stanic: {len(nalezene)}")


# ---------- Vyhledávání jevů v čase (--co dest / teplota) ----------

def parse_kolik(s):
    """Z řetězce typu '>=35' nebo '0,2' vrátí (porovnávací_funkce, operátor,
    práh). Chybí-li operátor, použije se '>='."""
    m = re.match(r"^\s*(>=|<=|==|=|>|<)?\s*(-?\d+(?:[.,]\d+)?)\s*$", s)
    if not m:
        raise ValueError(f"nesrozumitelný práh „{s}“ (zkus např. \">=35\")")
    op = m.group(1) or ">="
    prah = float(m.group(2).replace(",", "."))
    return OPERATORY[op], op, prah


def parse_datum(s):
    """Z řetězce '13.06.2026' nebo '2026-06-13' vrátí date."""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"nesrozumitelné datum „{s}“ "
                     f"(zkus 13.06.2026 nebo 2026-06-13)")


def stahni(url):
    """Vrátí naparsovaný JSON, nebo None pokud soubor neexistuje (404)."""
    r = SESSION.get(url, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def hodnoty_z_payloadu(payload, element, dt_index, val_index):
    """Z JSON payloadu vytáhne dvojice (datetime, hodnota) pro daný element,
    seřazené sestupně podle času (nejnovější první). Sloupce DT a VAL se berou
    podle zadaných indexů (liší se mezi 10min a denními daty)."""
    zaznamy = []
    for row in payload["data"]["data"]["values"]:
        if row[1] != element:
            continue
        hodnota = row[val_index]
        if hodnota is None or hodnota == "":
            continue
        try:
            cislo = float(hodnota)
        except (TypeError, ValueError):
            continue  # nečíselná hodnota (např. prázdný svit v noci)
        cas = dt.datetime.fromisoformat(row[dt_index].replace("Z", "+00:00"))
        zaznamy.append((cas, cislo))
    zaznamy.sort(key=lambda z: z[0], reverse=True)
    return zaznamy


def _o_mesic_zpet(rok, mesic):
    mesic -= 1
    return (rok - 1, 12) if mesic == 0 else (rok, mesic)


def soubory_10min(wsi, horni, dolni, dnes):
    """Plán souborů 10min dat od nejnovějších po nejstarší. Vrací dvojice
    (archiv?, url): aktuální měsíc po dnech, starší měsíce po měsíčním souboru."""
    aktualni_prvni = dnes.replace(day=1)
    if horni >= aktualni_prvni:
        den = horni
        while den >= aktualni_prvni and (dolni is None or den >= dolni):
            yield (False, f"Stahuji data za {den:%d.%m.%Y}",
                   f"{BASE_10MIN}10m-{wsi}-{den:%Y%m%d}.json")
            den -= dt.timedelta(days=1)
        rok, mesic = _o_mesic_zpet(aktualni_prvni.year, aktualni_prvni.month)
    else:
        rok, mesic = horni.year, horni.month

    for _ in range(MAX_MESICU_ZPET):
        if dolni is not None and (rok, mesic) < (dolni.year, dolni.month):
            break
        yield (True, f"Stahuji data za {rok}-{mesic:02d}",
               f"{BASE_10MIN}{mesic:02d}/10m-{wsi}-{rok:04d}{mesic:02d}.json")
        rok, mesic = _o_mesic_zpet(rok, mesic)


def soubory_denni(wsi, horni, dolni, dnes):
    """Plán souborů denních dat – jeden soubor na měsíc (aktuální měsíc v kořeni,
    starší měsíce v podsložce MM/), od nejnovějšího po nejstarší."""
    aktualni = (dnes.year, dnes.month)
    rok, mesic = horni.year, horni.month
    for _ in range(MAX_MESICU_ZPET):
        if dolni is not None and (rok, mesic) < (dolni.year, dolni.month):
            break
        oznam = f"Stahuji data za {rok}-{mesic:02d}"
        if (rok, mesic) == aktualni:
            yield False, oznam, f"{BASE_DENNI}dly-{wsi}-{rok:04d}{mesic:02d}.json"
        else:
            yield (True, oznam,
                   f"{BASE_DENNI}{mesic:02d}/dly-{wsi}-{rok:04d}{mesic:02d}.json")
        rok, mesic = _o_mesic_zpet(rok, mesic)


def zaznamy_zpet(zdroj, wsi, element, od_dt=None, do_dt=None):
    """Líně generuje záznamy (datetime, hodnota) od nejnovějších po nejstarší
    z daného zdroje. Soubory stahuje až ve chvíli, kdy jsou potřeba.

    Volitelné meze od_dt/do_dt (aware datetime) omezí jak rozsah vydaných
    záznamů, tak rozsah stahovaných souborů – díky tomu se neprochází celý
    archiv."""
    def v_rozsahu(cas):
        return ((od_dt is None or cas >= od_dt)
                and (do_dt is None or cas <= do_dt))

    dnes = dt.datetime.now(dt.timezone.utc).date()
    horni = dnes if do_dt is None else min(
        dnes, do_dt.astimezone(dt.timezone.utc).date())
    dolni = None if od_dt is None else od_dt.astimezone(dt.timezone.utc).date()

    dt_i, val_i = zdroj["dt_index"], zdroj["val_index"]
    for archiv, oznam, url in zdroj["soubory"](wsi, horni, dolni, dnes):
        _oznam(oznam)
        payload = stahni(url)
        if payload is None:
            if archiv:
                break  # archiv končí – starší data nemáme
            continue   # chybějící aktuální soubor (např. den) přeskočíme
        for cas, val in hodnoty_z_payloadu(payload, element, dt_i, val_i):
            if v_rozsahu(cas):
                yield cas, val


# Definice zdrojů archivu. `dt_index`/`val_index` udávají sloupce DT a VAL,
# `denni` přepíná zobrazení (datumy + délka ve dnech místo času).
ZDROJE = {
    "10min": {
        "krok": KROK_10MIN, "dt_index": 2, "val_index": 3,
        "soubory": soubory_10min, "denni": False, "jevy": JEVY_10MIN,
    },
    "denni": {
        "krok": KROK_DENNI, "dt_index": 3, "val_index": 4,
        "soubory": soubory_denni, "denni": True, "jevy": JEVY_DENNI,
    },
}


def najdi_epizody(zdroj, wsi, element, podminka, hloubka, limit,
                  od_dt=None, do_dt=None, prevod=None):
    """Najde až `hloubka` po sobě jdoucích epizod (směrem do minulosti), kdy
    `podminka(hodnota)` platí. `limit` je největší přípustný časový rozestup
    mezi sousedními výskyty téže epizody. Volitelné od_dt/do_dt omezí rozsah,
    `prevod` přepočítá surovou hodnotu (např. sekundy svitu na minuty).
    Vrací seznam (zacatek, konec, hodnoty) v UTC od nejnovější po nejstarší."""
    epizody = []
    konec = zacatek = None
    hodnoty = []

    for cas, val in zaznamy_zpet(zdroj, wsi, element, od_dt, do_dt):
        if prevod is not None:
            val = prevod(val)
        jev = podminka(val)
        if konec is None:
            # Hledáme konec další epizody = poslední výskyt splňující podmínku.
            if jev:
                konec = zacatek = cas
                hodnoty = [val]
            continue

        # Epizodu rozšiřujeme do minulosti, dokud jev (s tolerancí) trvá.
        if zacatek - cas <= limit:
            if jev:
                zacatek = cas
                hodnoty.append(val)
            continue

        # Přestávka delší než limit – aktuální epizoda končí.
        epizody.append((zacatek, konec, hodnoty))
        konec = zacatek = None
        hodnoty = []
        if len(epizody) >= hloubka:
            break
        # Tento záznam už může být koncem následující (starší) epizody.
        if jev:
            konec = zacatek = cas
            hodnoty = [val]

    # Epizoda rozpracovaná ve chvíli, kdy došla data.
    if konec is not None and len(epizody) < hloubka:
        epizody.append((zacatek, konec, hodnoty))

    return epizody


def popis_delky(delta, denni):
    """Naformátuje dobu trvání. U denních dat ve dnech (1 den / 2 dny / 5 dní),
    jinak v hodinách a minutách."""
    if denni:
        dny = round(delta.total_seconds() / 86400)
        if dny == 1:
            return "1 den"
        if 2 <= dny <= 4:
            return f"{dny} dny"
        return f"{dny} dní"
    minuty = int(delta.total_seconds() // 60)
    h, m = divmod(minuty, 60)
    if h and m:
        return f"{h} h {m} min"
    if h:
        return f"{h} h"
    return f"{m} min"


def formatuj_rozsah(zacatek, konec, krok, denni):
    """Vrátí rozsah epizody v místním čase. U denních dat jen data, u 10min
    časy (epizoda pokrývá interval od začátku - krok do konce posledního
    záznamu)."""
    if denni:
        z_loc, k_loc = zacatek.astimezone(), konec.astimezone()
        if z_loc.date() == k_loc.date():
            return f"{z_loc:%d.%m.%Y}"
        return f"{z_loc:%d.%m.%Y} – {k_loc:%d.%m.%Y}"
    z_loc = (zacatek - krok).astimezone()
    k_loc = konec.astimezone()
    if z_loc.date() == k_loc.date():
        return f"{z_loc:%d.%m.%Y %H:%M} – {k_loc:%H:%M}"
    return f"{z_loc:%d.%m.%Y %H:%M} – {k_loc:%d.%m.%Y %H:%M}"


def main():
    global PRUBEH
    parser = argparse.ArgumentParser(
        description="Najde poslední epizody meteorologického jevu na stanici "
                    "ČHMÚ.")
    parser.add_argument("--kde", required=True,
                        help="WSI kód stanice; u --co stanice část názvu nebo "
                             "kódu k vyhledání (např. \"Brno\")")
    vsechny_jevy = sorted(set(JEVY_10MIN) | set(JEVY_DENNI))
    parser.add_argument("-c", "--co", required=True,
                        choices=vsechny_jevy + ["stanice"],
                        help="co hledat: stanice, nebo počasí (dest, teplota, "
                             "mraz, vitr, vlhko, slunce, snih) – dostupnost "
                             "závisí na --zdroj")
    parser.add_argument("-z", "--zdroj", choices=sorted(ZDROJE), default="10min",
                        help="zdroj dat: 10min (výchozí) nebo denni "
                             "(denní agregáty: sníh, denní úhrny, epizoda = dny)")
    parser.add_argument("-k", "--kolik",
                        help="práh hodnoty s operátorem, např. \">=35\" "
                             "(povinné pro teplotu, u deště volitelné – "
                             "výchozí je úhrn > 0)")
    parser.add_argument("-d", "--hloubka", type=int, default=1,
                        help="kolik po sobě jdoucích epizod zpětně hledat "
                             "(výchozí 1)")
    parser.add_argument("-m", "--maximalni_prodleva", type=int, default=0,
                        help="max. přestávka v minutách, kterou epizoda ještě "
                             "snese (výchozí 0 = jakékoliv přerušení epizodu "
                             "ukončí)")
    parser.add_argument("--od",
                        help="hledat jen od tohoto data (např. 13.06.2026); "
                             "omezí prohledávaný rozsah")
    parser.add_argument("--do",
                        help="hledat jen do tohoto data (např. 16.06.2026)")
    args = parser.parse_args()

    # Vyhledávání stanic má jinou logiku – --kde je hledaný název/kód.
    if args.co == "stanice":
        PRUBEH = Prubeh()
        PRUBEH.start("Načítám seznam stanic")
        try:
            nalezene = hledej_stanice(args.kde)
        finally:
            PRUBEH.hotovo()
        vypis_stanice(nalezene, args.kde)
        return

    if args.hloubka < 1:
        parser.error("--hloubka musí být alespoň 1")
    if args.maximalni_prodleva < 0:
        parser.error("--maximalni_prodleva nesmí být záporná")

    zdroj = ZDROJE[args.zdroj]
    if args.co not in zdroj["jevy"]:
        dostupne = ", ".join(sorted(zdroj["jevy"]))
        parser.error(f"jev „{args.co}“ není ve zdroji {args.zdroj} dostupný "
                     f"(dostupné: {dostupne})")
    jev = zdroj["jevy"][args.co]
    if args.kolik:
        try:
            cmp, op, prah = parse_kolik(args.kolik)
        except ValueError as e:
            parser.error(str(e))
    elif jev["vyzaduje_kolik"]:
        parser.error(f"pro --co {args.co} je nutné zadat --kolik (např. \">=35\")")
    else:
        cmp, op, prah = jev["vychozi"]

    # Volitelné meze rozsahu: --od od půlnoci, --do do konce dne (místní čas).
    od_dt = do_dt = None
    try:
        if args.od:
            od_dt = dt.datetime.combine(parse_datum(args.od),
                                        dt.time.min).astimezone()
        if args.do:
            do_dt = dt.datetime.combine(parse_datum(args.do),
                                        dt.time.max).astimezone()
    except ValueError as e:
        parser.error(str(e))
    if od_dt and do_dt and od_dt > do_dt:
        parser.error("--od je pozdější než --do")

    krok, denni = zdroj["krok"], zdroj["denni"]
    podminka = lambda v: cmp(v, prah)
    limit = krok + dt.timedelta(minutes=args.maximalni_prodleva)
    popis = f"{jev['popis']} {op} {prah:g} {jev['jednotka']}"

    PRUBEH = Prubeh()
    PRUBEH.start("Stahuji data")
    try:
        epizody = najdi_epizody(zdroj, args.kde, jev["element"], podminka,
                                args.hloubka, limit, od_dt, do_dt,
                                jev.get("prevod"))
    finally:
        PRUBEH.hotovo()

    if not epizody:
        print(f"Stanice {args.kde}: pro podmínku {popis} nebyl v dostupných "
              f"datech (archiv ČHMÚ) nalezen žádný výskyt.")
        return

    if args.hloubka == 1:
        zacatek, konec, hodnoty = epizody[0]
        delka = (konec - zacatek) + krok
        souhrn = jev["souhrn_fn"](hodnoty)
        print(f"Stanice {args.kde}: {popis}")
        print(f"{jev['veta']} {formatuj_rozsah(zacatek, konec, krok, denni)} "
              f"(místní čas)")
        print(f"Délka: {popis_delky(delka, denni)}")
        print(f"{jev['souhrn_label'].capitalize()}: {souhrn:g} {jev['jednotka']}")
        return

    print(f"Stanice {args.kde}: {popis} — posledních {len(epizody)} epizod "
          f"(místní čas):")
    for i, (zacatek, konec, hodnoty) in enumerate(epizody, 1):
        delka = (konec - zacatek) + krok
        souhrn = jev["souhrn_fn"](hodnoty)
        print(f"{i}. {formatuj_rozsah(zacatek, konec, krok, denni)}  "
              f"(délka {popis_delky(delka, denni)}, {jev['souhrn_label']} "
              f"{souhrn:g} {jev['jednotka']})")


if __name__ == "__main__":
    main()
