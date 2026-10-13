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
def ping():
    "Vérifie que le serveur Form D répond."
    return "pong"


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


if __name__ == "__main__":
    mcp.run()
