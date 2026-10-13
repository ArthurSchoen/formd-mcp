import sqlite3
from datetime import datetime
from pathlib import Path

RAW_DB = Path.home() / "Code/Data_thesis/data/raw/formd/formd_all.sqlite"
CLEAN_DB = Path(__file__).parent / "data" / "formd_clean.sqlite"

FUND_INDUSTRIES = {"Pooled Investment Fund", "Investing", "REITS and Finance"}
PREVIOUS_NAME_COLUMNS = [
    "ISSUER_PREVIOUSNAME_1", "ISSUER_PREVIOUSNAME_2", "ISSUER_PREVIOUSNAME_3",
    "EDGAR_PREVIOUSNAME_1", "EDGAR_PREVIOUSNAME_2", "EDGAR_PREVIOUSNAME_3",
]

# Une ligne par dépôt : on ne garde que l'émetteur principal.
QUERY_FILINGS = """
SELECT s.ACCESSIONNUMBER, s.FILING_DATE, s.SUBMISSIONTYPE,
       i.CIK, i.ENTITYNAME, i.JURISDICTIONOFINC,
       i.YEAROFINC_TIMESPAN_CHOICE, i.YEAROFINC_VALUE_ENTERED,
       i.ISSUER_PREVIOUSNAME_1, i.ISSUER_PREVIOUSNAME_2, i.ISSUER_PREVIOUSNAME_3,
       i.EDGAR_PREVIOUSNAME_1, i.EDGAR_PREVIOUSNAME_2, i.EDGAR_PREVIOUSNAME_3,
       o.INDUSTRYGROUPTYPE, o.ISPOOLEDINVESTMENTFUNDTYPE, o.ISEQUITYTYPE,
       o.PREVIOUSACCESSIONNUMBER, o.SALE_DATE, o.YETTOOCCUR,
       o.TOTALAMOUNTSOLD, o.TOTALOFFERINGAMOUNT, o.TOTALNUMBERALREADYINVESTED
FROM formdsubmission s
JOIN issuers i ON i.ACCESSIONNUMBER = s.ACCESSIONNUMBER
JOIN offering o ON o.ACCESSIONNUMBER = s.ACCESSIONNUMBER
WHERE i.IS_PRIMARYISSUER_FLAG = 'YES'
"""

# Noms et rôles seulement : les adresses ne sortent jamais de la base brute.
QUERY_PEOPLE = """
SELECT ACCESSIONNUMBER, FIRSTNAME, LASTNAME,
       RELATIONSHIP_1, RELATIONSHIP_2, RELATIONSHIP_3
FROM relatedpersons
"""

SCHEMA = """
DROP TABLE IF EXISTS filings;
DROP TABLE IF EXISTS people;

CREATE TABLE filings (
    accession          TEXT PRIMARY KEY,
    cik                TEXT,
    entity_name        TEXT,
    previous_names     TEXT,
    state_inc          TEXT,
    year_inc           INTEGER,
    industry           TEXT,
    is_fund            INTEGER,
    is_equity          INTEGER,
    is_amendment       INTEGER,
    previous_accession TEXT,
    filing_date        TEXT,
    first_sale_date    TEXT,
    amount_sold        REAL,
    offering_amount    REAL,
    n_investors        INTEGER
);

CREATE TABLE people (
    accession  TEXT,
    first_name TEXT,
    last_name  TEXT,
    roles      TEXT
);
"""

INSERT_FILING = """
INSERT INTO filings VALUES (
    :accession, :cik, :entity_name, :previous_names, :state_inc, :year_inc,
    :industry, :is_fund, :is_equity, :is_amendment, :previous_accession,
    :filing_date, :first_sale_date, :amount_sold, :offering_amount, :n_investors
)
"""

INSERT_PERSON = """
INSERT INTO people VALUES (:accession, :first_name, :last_name, :roles)
"""

INDEXES = """
CREATE INDEX idx_filings_cik ON filings(cik);
CREATE INDEX idx_filings_date ON filings(filing_date);
CREATE INDEX idx_filings_name ON filings(entity_name COLLATE NOCASE);
CREATE INDEX idx_people_accession ON people(accession);
"""


def parse_date(texte):
    """Convertit une date Form D en AAAA-MM-JJ, ou None si vide."""
    if not texte:
        return None
    try:
        return datetime.strptime(texte, "%Y-%m-%d %H:%M:%S").date().isoformat()
    except ValueError:
        return datetime.strptime(texte, "%d-%b-%Y").date().isoformat()


def to_number(texte):
    if not texte or texte == 'Indefinite':
        return None
    return float(texte)


def to_bool(texte):
    if texte == "true":
        return 1
    return 0


def clean_filing(row):
    """Transforme une ligne brute en ligne propre pour la table filings."""
    within_five_years = row["YEAROFINC_TIMESPAN_CHOICE"] == "withinFiveYears"
    return {
        "accession": row["ACCESSIONNUMBER"],
        "cik": row["CIK"],
        "entity_name": row["ENTITYNAME"],
        "previous_names": " | ".join(row[c] for c in PREVIOUS_NAME_COLUMNS if row[c]) or None,
        "state_inc": row["JURISDICTIONOFINC"],
        "year_inc": int(row["YEAROFINC_VALUE_ENTERED"]) if within_five_years else None,
        "industry": row["INDUSTRYGROUPTYPE"],
        "is_fund": int(row["INDUSTRYGROUPTYPE"] in FUND_INDUSTRIES
                       or row["ISPOOLEDINVESTMENTFUNDTYPE"] == "true"),
        "is_equity": to_bool(row["ISEQUITYTYPE"]),
        "is_amendment": int(row["SUBMISSIONTYPE"] == "D/A"),
        "previous_accession": row["PREVIOUSACCESSIONNUMBER"],
        "filing_date": parse_date(row["FILING_DATE"]),
        "first_sale_date": None if row["YETTOOCCUR"] == "true" else row["SALE_DATE"],
        "amount_sold": to_number(row["TOTALAMOUNTSOLD"]),
        "offering_amount": to_number(row["TOTALOFFERINGAMOUNT"]),
        "n_investors": int(row["TOTALNUMBERALREADYINVESTED"]),
    }


def clean_person(row):
    """Garde le nom et réunit les trois rôles, par exemple « Executive Officer, Director »."""
    roles = [row["RELATIONSHIP_1"], row["RELATIONSHIP_2"], row["RELATIONSHIP_3"]]
    return {
        "accession": row["ACCESSIONNUMBER"],
        "first_name": row["FIRSTNAME"],
        "last_name": row["LASTNAME"],
        "roles": ", ".join(r for r in roles if r) or None,
    }


def make_db():
    """Lit la base brute en lecture seule et écrit la base propre."""
    CLEAN_DB.parent.mkdir(exist_ok=True)
    raw = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)
    raw.row_factory = sqlite3.Row
    clean = sqlite3.connect(CLEAN_DB)

    clean.executescript(SCHEMA)
    clean.executemany(INSERT_FILING, (clean_filing(r) for r in raw.execute(QUERY_FILINGS)))
    clean.executemany(INSERT_PERSON, (clean_person(r) for r in raw.execute(QUERY_PEOPLE)))
    clean.executescript(INDEXES)
    clean.commit()

    n_filings = clean.execute("SELECT count(*) FROM filings").fetchone()[0]
    n_people = clean.execute("SELECT count(*) FROM people").fetchone()[0]
    print(f"{CLEAN_DB} : {n_filings} dépôts, {n_people} personnes")
    raw.close()
    clean.close()


if __name__ == "__main__":
    make_db()
