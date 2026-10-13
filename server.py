import re
import sqlite3
from datetime import date

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from make_db import CLEAN_DB

mcp = FastMCP("formd")
MAX_LIMIT = 50


def connect():
    """Ouvre la base propre en lecture seule : le serveur ne modifie jamais rien."""
    con = sqlite3.connect(f"file:{CLEAN_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


_con = connect()
INDUSTRIES = sorted(r[0] for r in _con.execute("SELECT DISTINCT industry FROM filings"))
_con.close()


def check_date(texte, nom):
    """Refuse une date mal formée au lieu de renvoyer un résultat faux."""
    try:
        date.fromisoformat(texte)
    except ValueError:
        raise ToolError(f"{nom} doit être au format AAAA-MM-JJ, reçu : {texte!r}")


@mcp.tool
def search_form_d(industries: list[str] | None = None,
                  min_amount_usd: int | None = None,
                  since: str | None = None,
                  until: str | None = None,
                  include_funds: bool = False,
                  include_amendments: bool = False,
                  limit: int = 20) -> list[dict]:
    """Cherche des levées de fonds privées dans les dépôts Form D de la SEC (2017 à fin 2025).

    Résultats triés par montant vendu décroissant. Pour chaque dépôt : entity_name, cik,
    filing_date, industry, amount_sold, state_inc, accession.

    industries : un ou plusieurs secteurs, avec l'orthographe exacte de la liste fermée du
    Form D. « Tech » correspond à trois secteurs : Other Technology, Computers,
    Telecommunications. Un secteur inconnu renvoie la liste des 35 valeurs valides.
    min_amount_usd : montant minimum vendu, en DOLLARS et pas en millions :
    100 millions s'écrit 100000000.
    since, until : dates de dépôt au format AAAA-MM-JJ, bornes incluses.
    include_funds : False par défaut. Les fonds d'investissement font 62 % des dépôts et
    noieraient les résultats ; True pour les inclure.
    include_amendments : False par défaut. Un amendement redéclare une levée déjà déposée,
    donc la même levée apparaîtrait plusieurs fois. Le montant renvoyé est celui du dépôt
    initial : un amendement peut l'augmenter ensuite.
    limit : 20 par défaut, plafonné à 50.
    """
    where, params = [], []

    if industries:
        by_lower = {i.lower(): i for i in INDUSTRIES}
        unknown = [i for i in industries if i.lower() not in by_lower]
        if unknown:
            raise ToolError(f"Secteur inconnu : {unknown}. Valeurs valides : {INDUSTRIES}")
        exact = [by_lower[i.lower()] for i in industries]
        where.append(f"industry IN ({', '.join('?' * len(exact))})")
        params += exact
    if min_amount_usd is not None:
        where.append("amount_sold >= ?")
        params.append(min_amount_usd)
    if since:
        check_date(since, "since")
        where.append("filing_date >= ?")
        params.append(since)
    if until:
        check_date(until, "until")
        where.append("filing_date <= ?")
        params.append(until)
    if not include_funds:
        where.append("is_fund = 0")
    if not include_amendments:
        where.append("is_amendment = 0")

    sql = ("SELECT entity_name, cik, filing_date, industry, amount_sold, state_inc, accession "
           "FROM filings")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY amount_sold DESC LIMIT ?"
    params.append(max(1, min(limit, MAX_LIMIT)))

    con = connect()
    rows = [dict(r) for r in con.execute(sql, params)]
    con.close()
    return rows


MAX_CANDIDATES = 10


@mcp.tool
def find_issuer(name: str, include_funds: bool = False) -> list[dict]:
    """Cherche une société par son nom dans les dépôts Form D, sans tenir compte des majuscules.

    La recherche porte sur le nom légal actuel et sur les anciens noms. L'outil ne devine
    jamais : il renvoie jusqu'à 10 candidats, un par société (CIK), avec le nom légal le plus
    récent, l'État, le nombre de dépôts et la date du dernier dépôt. Le choix revient au
    modèle ou à l'utilisateur.

    Le nom légal diffère souvent de la marque (la marque Facebook correspond au nom légal
    Meta Platforms, Inc.). Si aucun candidat n'est la société voulue et que son nom légal
    est connu, relancer la recherche avec ce nom.

    include_funds : False par défaut. Un véhicule nommé d'après une société
    (« X Capital Fund, LP ») n'est pas cette société ; True pour inclure les fonds.

    Une liste vide veut dire qu'aucun dépôt ne correspond, pas que la société n'a pas levé :
    une levée sans Form D est fréquente.
    """
    sql = "SELECT * FROM filings WHERE (entity_name LIKE ? OR previous_names LIKE ?)"
    if not include_funds:
        sql += " AND is_fund = 0"
    pattern = f"%{name}%"
    con = connect()
    rows = con.execute(sql, (pattern, pattern)).fetchall()
    con.close()

    # LIKE cherche une sous-chaîne : « anthropic » trouverait « Philanthropic ».
    # On ne garde que les noms où la recherche commence un mot.
    word = re.compile(r"\b" + re.escape(name), re.IGNORECASE)
    companies = {}
    for r in rows:
        if not word.search(f"{r['entity_name']} | {r['previous_names'] or ''}"):
            continue
        c = companies.setdefault(r["cik"], {"n_filings": 0, "last": r})
        c["n_filings"] += 1
        if r["filing_date"] > c["last"]["filing_date"]:
            c["last"] = r

    candidates = [
        {
            "entity_name": c["last"]["entity_name"],
            "cik": cik,
            "state_inc": c["last"]["state_inc"],
            "previous_names": c["last"]["previous_names"],
            "n_filings": c["n_filings"],
            "last_filing_date": c["last"]["filing_date"],
        }
        for cik, c in companies.items()
    ]
    candidates.sort(key=lambda c: c["last_filing_date"], reverse=True)
    return candidates[:MAX_CANDIDATES]


@mcp.tool
def company_history(cik: str) -> dict:
    """Renvoie tout l'historique Form D d'une société, du dépôt le plus ancien au plus récent.

    cik : identifiant SEC de la société, donné par find_issuer (les zéros en tête sont
    facultatifs : 2023314 et 0002023314 sont équivalents).

    Pour chaque dépôt : filing_date, type (D pour un nouveau dépôt, D/A pour un amendement
    qui corrige ou met à jour un dépôt précédent), amount_sold en dollars, n_investors,
    industry, is_fund (1 si le dépôt est celui d'un fonds), accession.
    people : noms et rôles des personnes déclarées sur le dépôt le plus récent.
    """
    cik = cik.strip().zfill(10)
    con = connect()
    filings = [dict(r) for r in con.execute(
        "SELECT filing_date, CASE is_amendment WHEN 1 THEN 'D/A' ELSE 'D' END AS type, "
        "amount_sold, n_investors, industry, is_fund, accession, entity_name "
        "FROM filings WHERE cik = ? ORDER BY filing_date, accession", (cik,))]
    if not filings:
        con.close()
        raise ToolError(f"Aucun dépôt pour le CIK {cik}. Utiliser find_issuer pour trouver le CIK à partir d'un nom.")
    latest = filings[-1]
    entity_name = latest["entity_name"]
    people = [dict(r) for r in con.execute(
        "SELECT first_name, last_name, roles FROM people WHERE accession = ?", (latest["accession"],))]
    con.close()
    for f in filings:
        del f["entity_name"]
    return {"entity_name": entity_name, "cik": cik, "filings": filings, "people": people}


if __name__ == "__main__":
    mcp.run()
