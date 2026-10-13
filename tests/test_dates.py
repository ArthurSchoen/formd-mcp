from make_db import parse_date

def test_format_2021_2025():
    assert parse_date("01-DEC-2025") == "2025-12-01"


def test_format_2017_2020():
    assert parse_date("2017-03-31 17:23:01") == "2017-03-31"


def test_vide():
    assert parse_date(None) == None


