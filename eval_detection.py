"""Mesure la détection des Séries A : taux retrouvé, échantillon à vérifier, volume.

1. Taux de Séries A retrouvées : les startups de la thèse, reliées à un CIK par leur nom,
   ont-elles une détection à 120 jours près de leur date de Série A ?
2. Taux de détections justes : tire 30 détections de 2025 dans docs/precision_2025.csv.
   Arthur remplit la colonne verdict à la main ; le script calcule alors le taux.
3. Volume : nombre de Séries A probables par semaine en 2025.
"""

import csv
import random
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

from make_db import CLEAN_DB
from series_a import detect

THESIS_CSV = Path.home() / "Code/Data_thesis/data/processed/final_dataset_full.csv"
SAMPLE_CSV = Path(__file__).parent / "docs" / "precision_2025.csv"
WINDOW_DAYS = 120
SUFFIXES = {"inc", "incorporated", "llc", "corp", "corporation", "co", "company",
            "ltd", "limited", "lp", "plc", "pbc", "the"}


def normalize(name: str) -> str:
    """Minuscules, sans ponctuation, sans « inc », « llc », etc."""
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def name_to_ciks(con) -> dict[str, set[str]]:
    """Relie chaque nom normalisé (actuel ou ancien) aux CIK qui l'ont porté, hors fonds."""
    index = {}
    for cik, name, previous in con.execute(
            "SELECT DISTINCT cik, entity_name, previous_names FROM filings WHERE is_fund = 0"):
        for n in [name] + (previous.split(" | ") if previous else []):
            if n:
                index.setdefault(normalize(n), set()).add(cik)
    return index


def recall(con, detections: list[dict]) -> dict:
    by_cik = {}
    for d in detections:
        if d["probable"]:
            by_cik.setdefault(d["cik"], []).append(date.fromisoformat(d["filing_date"]))

    index = name_to_ciks(con)
    counts = Counter()
    for row in csv.DictReader(open(THESIS_CSV)):
        if not row["seriesA_date"] or row["seriesA_date"] < "2017-01-01":
            counts["hors période de la base"] += 1
            continue
        ciks = index.get(normalize(row["Organization_Name"]), set())
        if len(ciks) != 1:
            counts["aucun CIK" if not ciks else "plusieurs CIK"] += 1
            continue
        counts["reliées à un seul CIK"] += 1
        a_date = date.fromisoformat(row["seriesA_date"][:10])
        if any(abs((d - a_date).days) <= WINDOW_DAYS for d in by_cik.get(ciks.pop(), [])):
            counts["retrouvées"] += 1
    return counts


def precision_sample(detections: list[dict]) -> None:
    """Écrit 30 détections de 2025 tirées au hasard, sauf si des verdicts sont déjà remplis."""
    if SAMPLE_CSV.exists() and precision() is not None:
        return
    pool = [d for d in detections if d["probable"] and d["filing_date"] >= "2025-01-01"]
    sample = random.Random(42).sample(pool, 30)
    SAMPLE_CSV.parent.mkdir(exist_ok=True)
    with open(SAMPLE_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["entity_name", "filing_date", "amount_sold", "score", "reasons",
                    "edgar", "verdict", "note"])
        for d in sorted(sample, key=lambda d: d["filing_date"]):
            w.writerow([d["entity_name"], d["filing_date"], int(d["amount_sold"]), d["score"],
                        " ; ".join(d["reasons"]),
                        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={d['cik']}&type=D",
                        "", ""])


def precision() -> tuple[int, int] | None:
    """Renvoie (justes, vérifiées) si Arthur a rempli des verdicts, sinon None."""
    rows = [r for r in csv.DictReader(open(SAMPLE_CSV)) if r["verdict"].strip()]
    if not rows:
        return None
    return sum(r["verdict"].strip().lower() == "a" for r in rows), len(rows)


def weekly_volume(detections: list[dict]) -> Counter:
    weeks = Counter()
    for d in detections:
        if d["probable"] and d["filing_date"].startswith("2025"):
            weeks[date.fromisoformat(d["filing_date"]).isocalendar()[1]] += 1
    return weeks


def main():
    con = sqlite3.connect(f"file:{CLEAN_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    detections = detect(con, "2017-01-01", "2025-12-31")

    counts = recall(con, detections)
    linked, found = counts["reliées à un seul CIK"], counts["retrouvées"]
    print("1. Séries A de la thèse retrouvées")
    for k, v in counts.items():
        print(f"   {k} : {v}")
    print(f"   taux : {found} / {linked} = {found / linked:.1%}")

    precision_sample(detections)
    p = precision()
    print("2. Détections justes (échantillon de 30, 2025)")
    print(f"   {p[0]} / {p[1]} = {p[0] / p[1]:.1%}" if p else f"   à remplir à la main : {SAMPLE_CSV}")

    weeks = weekly_volume(detections)
    values = [weeks.get(w, 0) for w in range(1, 53)]
    print("3. Séries A probables par semaine en 2025")
    print(f"   moyenne {sum(values) / 52:.0f}, min {min(values)}, max {max(values)}, total {sum(values)}")
    con.close()


if __name__ == "__main__":
    main()
