#!/usr/bin/env python3
"""Import dat z liga-stahovatko.js pro stránku docs/extraliga-bilance.html.

Použití:  python scripts/liga_tymy.py [soubor.json ...]
Bez parametrů zpracuje všechny scripts/liga_raw/liga_*.json.

Pro každý klub vznikne docs/liga/<KOD>.json (kompaktní řádky zápasů bruslařů a zvlášť brankářů) a obnoví se
docs/liga/index.json (seznam klubů). Zápasy se berou jen z extraligy včetně play off
(stejný filtr jako u Motoru). Při opakovaném importu se sezóny, které soubor obsahuje,
nahradí novými a starší zůstanou (rychlý režim stahovátka tedy nic nesmaže).

Řádek v souboru: [dt, kolo, soutěž, domácí, hosté, skóre D, skóre H, prodl.(0/1),
                  G, A, B, +/-, TM, TOI(s), sezóna]
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
RAW_DIR = SCRIPT_DIR / "liga_raw"
OUT_DIR = SCRIPT_DIR.parent / "docs" / "liga"

COMP_RE = re.compile(r"extralig|^(Generali\s+)?(Česká pojišťovna\s+)?play\s*-?\s*off", re.I)
COMP_EXCLUDE_RE = re.compile(r"junior|dorost|9\. tříd|U\d\d|\bml\.|\bst\.|baráž", re.I)


def comp_wanted(comp: str) -> bool:
    return bool(COMP_RE.search(comp)) and not COMP_EXCLUDE_RE.search(comp)


def kompakt(r: dict, season: int) -> list:
    return [r["dt"], r.get("kolo", ""), r.get("comp", ""), r["a"], r["b"],
            r.get("sa"), r.get("sb"), 1 if r.get("ot") else 0,
            r.get("g", 0), r.get("as", 0), r.get("p", 0), r.get("pm", 0), r.get("tm", 0),
            r.get("toi", 0), season]


def je_brankar(rows: list) -> bool:
    """Brankář: hokej.cz mu ve sloupci „góly“ vede odehrané minuty (kolem 60), bruslař nemá 10+ gólů za zápas."""
    if not rows:
        return False
    return sum(1 for r in rows if r[8] >= 10) / len(rows) > 0.3


def kod_klubu(hraci: dict) -> str | None:
    """Kód klubu = tým, který se nejčastěji vyskytuje v posledních zápasech hráčů souboru."""
    c = Counter()
    for rows in hraci.values():
        for r in sorted(rows, key=lambda x: x[0])[-15:]:
            c[r[3]] += 1
            c[r[4]] += 1
    return c.most_common(1)[0][0] if c else None


def sloucit(nove: dict, stare: dict, idy: dict, stare_idy: dict, sezony: dict) -> None:
    """Přidá do `nove` hráče ze `stare`: neznámé celé, známé (stejné id) jen o sezóny, které nový soubor neobsahuje."""
    for name, rows in stare.items():
        sid = stare_idy.get(name)
        shoda = next((n for n in nove if sid and idy.get(n) == sid), None)
        if shoda is None:
            nove[name] = rows
            idy[name] = sid
        else:
            drzet = [r for r in rows if r[14] not in sezony.get(shoda, set())]
            nove[shoda] = sorted(nove[shoda] + drzet, key=lambda x: x[0])


def zpracuj_soubor(raw_file: Path) -> None:
    """Jeden soubor = jeden klub (liga-stahovatko.js) nebo celá liga (liga-aktualizace.js, klíč _vse)."""
    raw = json.loads(raw_file.read_text(encoding="utf-8"))
    casti = raw["_vse"] if isinstance(raw.get("_vse"), list) else [raw]
    for i, cast in enumerate(casti, 1):
        zpracuj(cast, raw_file.name if len(casti) == 1 else f"{raw_file.name}#{i}")


def zpracuj(raw: dict, popis: str) -> dict | None:
    klub = raw.pop("_klub", {}) or {}
    raw.pop("_zapasy", None)
    hraci, brankari, idy, sezony_hrace = {}, {}, {}, {}
    for path, e in raw.items():
        rows, sezony = [], set()
        for s, v in e.get("sezony", {}).items():
            sezony.add(int(s))
            for r in v.get("radky", []):
                if comp_wanted(r.get("comp", "")):
                    rows.append(kompakt(r, int(s)))
        if not rows:
            continue  # hráči bez extraligových zápasů
        name = e.get("jmeno") or path
        cil = brankari if je_brankar(rows) else hraci
        if name in hraci or name in brankari:
            name = f"{name} ({path.rsplit('/', 1)[-1]})"
        cil[name] = sorted(rows, key=lambda x: x[0])
        idy[name] = path
        sezony_hrace[name] = sezony
    if not hraci:
        print(f"  {popis}: žádní bruslaři, přeskočeno")
        return None
    kod = kod_klubu(hraci)
    out_file = OUT_DIR / f"{kod}.json"
    stary = {}
    if out_file.exists():
        try:
            stary = json.loads(out_file.read_text(encoding="utf-8"))
        except Exception:
            stary = {}
    sid_old = stary.get("idy", {})
    # sloučení: starší sezóny, které nový soubor neobsahuje, zůstanou
    sloucit(hraci, {n: r for n, r in stary.get("hraci", {}).items() if not je_brankar(r)}, idy, sid_old, sezony_hrace)
    star_br = dict(stary.get("brankari", {}))
    star_br.update({n: r for n, r in stary.get("hraci", {}).items() if je_brankar(r)})  # dříve uložení brankáři mezi bruslaři
    sloucit(brankari, star_br, idy, sid_old, sezony_hrace)
    out = {"kod": kod, "nazev": klub.get("nazev") or stary.get("nazev") or kod,
           "slug": klub.get("slug") or stary.get("slug"),
           "vygenerovano": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "hraci": hraci, "brankari": brankari, "idy": idy}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {popis} → {kod}: {len(hraci)} bruslařů, {len(brankari)} brankářů, "
          f"{sum(len(r) for r in hraci.values())} řádků")
    return out


def index() -> None:
    kluby = []
    for f in sorted(OUT_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        kluby.append({"kod": d["kod"], "nazev": d["nazev"], "hracu": len(d["hraci"]), "brankaru": len(d.get("brankari", {})),
                      "radku": sum(len(r) for r in d["hraci"].values()),
                      "vygenerovano": d["vygenerovano"]})
    (OUT_DIR / "index.json").write_text(json.dumps(kluby, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"index.json: {len(kluby)} klubů")


# ------------------------------------------------------------ kontrola přiřazení zápasů
def tym_hrace(rows: list, home: str | None, cur: int) -> list:
    """Stejná logika jako inferTeams na stránce: tým hráče z po sobě jdoucích zápasů v sezóně,
    pak pravidlo „aktuální sezóna proti vlastnímu klubu“ a odhad podle nejbližšího jasného zápasu.
    Vrací [{r, team, stav}] kde stav je None / "odhad" / "nepřiřazeno"."""
    items = [{"r": r, "a": r[3], "b": r[4], "season": r[14], "team": None, "amb": False, "odhad": False} for r in rows]
    by = {}
    for x in items:
        by.setdefault(x["season"], []).append(x)
    for g in by.values():
        g.sort(key=lambda x: x["r"][0])
        run, cand = [], None

        def flush():
            nonlocal run, cand
            if run:
                t = cand[0] if cand and len(cand) == 1 else None
                for x in run:
                    x["team"], x["amb"] = t, t is None
            run, cand = [], None

        for x in g:
            sx = [x["a"], x["b"]]
            if cand is None:
                cand, run = sx, [x]
                continue
            inter = [c for c in cand if c in sx]
            if inter:
                cand = inter
                run.append(x)
            else:
                flush()
                cand, run = sx, [x]
        flush()
    for x in items:
        if x["amb"] and home and x["season"] == cur and home in (x["a"], x["b"]):
            x["team"], x["amb"] = home, False
    srt = sorted(items, key=lambda x: x["r"][0])
    for i, x in enumerate(srt):
        if x["team"] or not x["amb"]:
            continue
        t = next((srt[j]["team"] for j in range(i - 1, -1, -1) if srt[j]["team"]), None)
        if t not in (x["a"], x["b"]):
            t = next((srt[j]["team"] for j in range(i + 1, len(srt)) if srt[j]["team"]), None)
        if t in (x["a"], x["b"]):
            x["team"], x["amb"], x["odhad"] = t, False, True
    for x in items:
        x["stav"] = "nepřiřazeno" if x["amb"] else ("odhad" if x["odhad"] else None)
    return items


def kontrola_prirazeni() -> None:
    """Vyrobí docs/liga/nejasne.csv (jeden řádek = jeden nejasný zápas) a nejasne_hraci.csv (souhrn podle hráčů).
    Hráč, který je v souborech dvou klubů (přestup), se před kontrolou sloučí a patří klubu s posledním zápasem."""
    hraci = {}
    cur = 0
    for f in sorted(OUT_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        for poz, klic in (("bruslař", "hraci"), ("brankář", "brankari")):
            for name, rows in d.get(klic, {}).items():
                key = (d.get("idy", {}).get(name) or f"{d['kod']}:{name}", poz)
                e = hraci.setdefault(key, {"name": name, "poz": poz, "rows": {}, "klub": d["kod"], "last": ""})
                for r in rows:
                    e["rows"].setdefault((r[0], r[3], r[4]), r)
                    cur = max(cur, r[14])
                last = max((r[0] for r in rows), default="")
                if last > e["last"]:
                    e["last"], e["klub"] = last, d["kod"]
    radky, souhrn = [], {}
    for e in hraci.values():
        for x in tym_hrace(list(e["rows"].values()), e["klub"], cur):
            if not x["stav"]:
                continue
            r = x["r"]
            body = r[10] if e["poz"] == "bruslař" else ""
            radky.append([e["klub"], e["name"], e["poz"], r[0], r[14], f"{r[3]} – {r[4]}",
                          f"{r[5]}:{r[6]}" if r[5] is not None else "", x["stav"],
                          x["team"] or f"{r[3]} nebo {r[4]}", body])
            sm = souhrn.setdefault((e["klub"], e["name"], e["poz"]), [0, 0])
            sm[0 if x["stav"] == "nepřiřazeno" else 1] += 1
    radky.sort(key=lambda z: (z[7] != "nepřiřazeno", z[0], z[1], z[3]))

    def csv(hlavicka, data):
        esc = lambda v: '"' + str(v).replace('"', '""') + '"'
        return "\ufeff" + "\n".join(";".join(esc(c) for c in row) for row in [hlavicka] + data) + "\n"

    (OUT_DIR / "nejasne.csv").write_text(csv(
        ["Klub", "Hráč", "Pozice", "Datum", "Sezóna", "Zápas", "Skóre", "Stav", "Tým (odhad) / kandidáti", "Body v zápase"], radky),
        encoding="utf-8")
    sh = sorted(([k[0], k[1], k[2], v[0], v[1], v[0] + v[1]] for k, v in souhrn.items()), key=lambda z: (-z[3], -z[5], z[0], z[1]))
    (OUT_DIR / "nejasne_hraci.csv").write_text(csv(
        ["Klub", "Hráč", "Pozice", "Nepřiřazeno", "Odhadem", "Celkem"], sh), encoding="utf-8")
    n_np = sum(1 for z in radky if z[7] == "nepřiřazeno")
    print(f"Kontrola přiřazení: {n_np} zápasů nepřiřazeno, {len(radky) - n_np} přiřazeno odhadem, "
          f"u {len(souhrn)} hráčů z {len(hraci)} (docs/liga/nejasne.csv).")
    for z in sh[:15]:
        print(f"   {z[0]:4} {z[1]:28} nepřiřazeno {z[3]}, odhadem {z[4]}")


def vycisti_stare() -> None:
    """Přesune z uložených klubů brankáře z bruslařů do samostatné části (bez nového stahování)."""
    for f in sorted(OUT_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        presun = [n for n, r in d["hraci"].items() if je_brankar(r)]
        for n in presun:
            d.setdefault("brankari", {})[n] = d["hraci"].pop(n)
        if presun:
            f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(f"  {f.name}: přesunuto brankářů {len(presun)} ({', '.join(presun)})")


def main() -> None:
    soubory = [Path(a) for a in sys.argv[1:]] or sorted(RAW_DIR.glob("liga_*.json"))
    if not soubory:
        print("Žádné nové vstupní soubory, jen čistím uložená data.")
        vycisti_stare()
        index()
        kontrola_prirazeni()
        return
    for f in soubory:
        zpracuj_soubor(f)
    index()
    kontrola_prirazeni()


if __name__ == "__main__":
    main()
