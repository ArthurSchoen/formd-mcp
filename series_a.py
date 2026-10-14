"""Estime si un dépôt Form D est une Série A, avec une règle à points.

Version simplifiée des règles de l'étape 01 de la thèse. Les seuils sont des
hypothèses, mesurées à l'étape 4.3.
"""

from datetime import date

# Médiane des Séries A par année, en dollars (thèse). La thèse n'a pas de chiffre
# après 2022 : 12 M$ est une hypothèse.
MEDIAN_SERIES_A = {2017: 7_000_000, 2018: 7_500_000, 2019: 7_000_000,
                   2020: 8_000_000, 2021: 12_000_000, 2022: 12_500_000}
DEFAULT_MEDIAN = 12_000_000

EXCLUDED_INDUSTRIES = {
    "Commercial", "Residential", "Other Real Estate",
    "Commercial Banking", "Investment Banking", "Insurance",
    "Other Banking and Financial Services", "Oil and Gas",
}

THRESHOLD = 4


def score_filing(filing: dict, previous: list[dict]) -> tuple[int | None, list[str]]:
    """Note un dépôt D et renvoie (score, raisons).

    filing : le dépôt à noter, un dictionnaire avec filing_date, amount_sold, is_fund,
    is_equity, industry, year_inc.
    previous : les dépôts antérieurs de la même société (D et D/A), avec les mêmes clés
    plus is_amendment.
    score vaut None si le dépôt est rejeté d'office. raisons explique chaque point.
    """
    # Rejets d'office
    if filing["is_fund"] or not filing["is_equity"]:
        return None, ["rejet : fonds ou pas d'equity"]
    if filing["industry"] in EXCLUDED_INDUSTRIES:
        return None, ["rejet : secteur hors cible"]
    amount = filing["amount_sold"]
    if amount < 2_000_000 or amount > 100_000_000:
        return None, ["rejet : montant hors de 2 à 100 M$"]

    # L'année n'est déclarée que pour les sociétés de moins de 5 ans :
    # si elle manque, on la reprend d'un dépôt plus ancien.
    day = date.fromisoformat(filing["filing_date"])
    year_inc = filing["year_inc"]
    if year_inc is None:
        for p in previous:
            if p["year_inc"] is not None:
                year_inc = p["year_inc"]
                break
    age = day.year - year_inc if year_inc is not None else None
    if age is not None and age > 12:
        return None, ["rejet : société de plus de 12 ans"]

    # Points
    score = 0
    reasons = []

    median = MEDIAN_SERIES_A.get(day.year, DEFAULT_MEDIAN)
    if 0.25 * median <= amount <= 2.5 * median:
        score += 2
        reasons.append("+2 montant typique d'une Série A de l'année")

    # L'âge est une différence d'années civiles : « 1 an » couvre de 1 à 23 mois.
    # Mesuré en 4.3 : la règle du guide (2 à 4 ans) ratait 157 Séries A de la thèse à 1 an.
    if age is not None and 1 <= age <= 4:
        score += 2
        reasons.append("+2 âge de 1 à 4 ans")
    elif age is not None and 5 <= age <= 6:
        score += 1
        reasons.append("+1 âge de 5 ou 6 ans")

    # Les amendements ne sont pas des levées : on ne compare qu'aux dépôts D.
    previous_d = [p for p in previous if not p["is_amendment"]]
    days_since = [(day - date.fromisoformat(p["filing_date"])).days for p in previous_d]

    if any(d >= 90 for d in days_since):
        score += 1
        reasons.append("+1 dépôt D antérieur d'au moins 90 jours")

    if previous_d:
        last = max(previous_d, key=lambda p: p["filing_date"])
        if last["amount_sold"]:
            ratio = amount / last["amount_sold"]
            if ratio >= 3:
                score += 2
                reasons.append(f"+2 hausse x{ratio:.1f} sur le dépôt précédent")
            elif ratio >= 2:
                score += 1
                reasons.append(f"+1 hausse x{ratio:.1f} sur le dépôt précédent")
            elif ratio < 0.5:
                score -= 1
                reasons.append(f"-1 baisse x{ratio:.1f} sur le dépôt précédent")

    for p, d in zip(previous_d, days_since):
        if d <= 365 and p["amount_sold"] and abs(amount - p["amount_sold"]) <= 0.5 * p["amount_sold"]:
            score -= 2
            reasons.append("-2 extension probable : montant proche moins d'un an avant")
            break

    return score, reasons


DETECT_QUERY = """
SELECT cik, entity_name, accession, filing_date, amount_sold, is_fund, is_equity,
       industry, year_inc, is_amendment
FROM filings
WHERE cik IN (SELECT cik FROM filings
              WHERE is_amendment = 0 AND is_fund = 0 AND filing_date BETWEEN ? AND ?)
ORDER BY cik, filing_date, accession
"""


def detect(con, since: str, until: str) -> list[dict]:
    """Note chaque dépôt D déposé entre since et until (inclus), avec l'historique de sa société.

    con : connexion à la base propre, avec row_factory = sqlite3.Row.
    Renvoie les dépôts non rejetés, avec score, raisons et probable (score >= THRESHOLD).
    """
    history = {}
    for row in con.execute(DETECT_QUERY, (since, until)):
        f = dict(row)
        history.setdefault(f["cik"], []).append(f)

    results = []
    for filings in history.values():
        for f in filings:
            if f["is_amendment"] or not (since <= f["filing_date"] <= until):
                continue
            previous = [p for p in filings if p["filing_date"] < f["filing_date"]]
            score, reasons = score_filing(f, previous)
            if score is not None:
                results.append({**f, "score": score, "reasons": reasons,
                                "probable": score >= THRESHOLD})
    return results
