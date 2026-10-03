import pytest
from insurai.retrieval.glossary import expand

pytestmark = pytest.mark.unit


def test_AC_04_07_drunk_driving_adds_intoxication() -> None:
    expanded, _ = expand("Is drunk driving covered?")
    assert "intoxication" in expanded
    assert expanded.startswith("Is drunk driving covered?")


def test_AC_04_07_ped_adds_pre_existing_disease() -> None:
    expanded, _ = expand("What is the waiting period for PED?")
    assert "pre-existing disease" in expanded


def test_AC_04_07_pregnancy_yields_hints_5_4() -> None:
    _, hints = expand("Is pregnancy covered?")
    assert hints[:2] == [5, 4]


def test_AC_04_07_matching_is_case_insensitive() -> None:
    expanded, _ = expand("is DRUNK DRIVING excluded")
    assert "intoxication" in expanded


def test_AC_04_07_word_boundary_speed_does_not_trigger_ped() -> None:
    expanded, _ = expand("What about speed limits on highways?")
    assert "pre-existing" not in expanded


def test_AC_04_07_terms_already_in_query_are_not_repeated() -> None:
    expanded, _ = expand("drunk driving or intoxication")
    assert expanded.lower().count("intoxication") == 1


def test_AC_04_07_no_match_leaves_query_and_no_hints() -> None:
    assert expand("hello there") == ("hello there", [])


def test_AC_04_07_hints_are_deduplicated_in_order() -> None:
    _, hints = expand("maternity and pregnancy waiting")
    assert hints == [5, 4]
