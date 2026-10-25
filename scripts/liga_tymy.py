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


def zpracuj(raw_file: Path) -> dict | None:
    raw = json.loads(raw_file.read_text(encoding="utf-8"))
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
        print(f"  {raw_file.name}: žádní bruslaři, přeskočeno")
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
    print(f"  {raw_file.name} → {kod}: {len(hraci)} bruslařů, {len(brankari)} brankářů, "
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
        return
    for f in soubory:
        zpracuj(f)
    index()


if __name__ == "__main__":
    main()
