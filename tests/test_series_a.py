from series_a import THRESHOLD, score_filing


def depot(date, montant, **autres):
    """Fabrique un dépôt de test : une startup tech créée en 2022, en equity, hors fonds."""
    d = {"filing_date": date, "amount_sold": montant, "is_fund": 0, "is_equity": 1,
         "industry": "Other Technology", "year_inc": 2022, "is_amendment": 0}
    d.update(autres)
    return d


def test_hauler_hero():
    # Les vrais dépôts de Hauler Hero (CIK 0002023314) : +2 montant, +2 âge,
    # +1 dépôt antérieur, +2 hausse de 250 k$ à 12 M$
    anciens = [depot("2024-05-14", 1_906_999, year_inc=2021),
               depot("2025-01-02", 250_000, year_inc=2021)]
    score, raisons = score_filing(depot("2025-12-01", 12_000_000, year_inc=2021), anciens)
    assert score == 7
    assert score >= THRESHOLD


def test_rejet_fonds():
    assert score_filing(depot("2025-06-01", 10_000_000, is_fund=1), [])[0] is None


def test_rejet_montant_trop_petit():
    assert score_filing(depot("2025-06-01", 1_500_000), [])[0] is None


def test_rejet_secteur():
    assert score_filing(depot("2025-06-01", 10_000_000, industry="Oil and Gas"), [])[0] is None


def test_premier_depot():
    # +2 montant typique, +2 âge (3 ans), aucun dépôt avant
    assert score_filing(depot("2025-06-01", 10_000_000), [])[0] == 4


def test_hausse_x3():
    # +2 montant, +2 âge, +1 dépôt antérieur, +2 hausse de 3 M$ à 10 M$
    anciens = [depot("2024-01-01", 3_000_000)]
    assert score_filing(depot("2025-06-01", 10_000_000), anciens)[0] == 7


def test_extension():
    # Montant proche six mois plus tôt : +2 montant, +2 âge, +1 dépôt antérieur, -2 extension
    anciens = [depot("2024-12-01", 9_000_000)]
    assert score_filing(depot("2025-06-01", 10_000_000), anciens)[0] == 3


def test_annee_reprise_d_un_ancien_depot():
    # Le dépôt de 2025 ne donne pas l'année ; celui de 2017 dit 2012 : 13 ans, rejet
    anciens = [depot("2017-03-01", 3_000_000, year_inc=2012)]
    assert score_filing(depot("2025-06-01", 10_000_000, year_inc=None), anciens)[0] is None


def test_ancien_montant_nul():
    # Un dépôt précédent à 0 $ ne doit pas faire planter la division
    anciens = [depot("2024-01-01", 0)]
    assert score_filing(depot("2025-06-01", 10_000_000), anciens)[0] == 5


def test_amendement_ignore():
    # Un amendement n'est pas une levée : pas de point « dépôt antérieur »
    anciens = [depot("2024-01-01", 3_000_000, is_amendment=1)]
    assert score_filing(depot("2025-06-01", 10_000_000), anciens)[0] == 4


def test_age_un_an():
    # Créée en 2024, dépôt en 2025 : « 1 an » en années civiles, +2 âge
    assert score_filing(depot("2025-06-01", 10_000_000, year_inc=2024), [])[0] == 4
