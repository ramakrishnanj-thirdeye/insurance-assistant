from decimal import Decimal

import pytest

from insurai.formatting import inr

pytestmark = pytest.mark.unit


def test_M0_inr_five_lakh() -> None:
    assert inr(500000) == "₹5,00,000"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "₹0"),
        (999, "₹999"),
        (1000, "₹1,000"),
        (100000, "₹1,00,000"),
        (236053, "₹2,36,053"),
        (12345678, "₹1,23,45,678"),
        (1234567890, "₹1,23,45,67,890"),
        (-5000, "-₹5,000"),
        (1234.5, "₹1,235"),
        (Decimal("2.5"), "₹3"),
    ],
)
def test_M0_inr_indian_digit_grouping(amount: int | float | Decimal, expected: str) -> None:
    assert inr(amount) == expected


def test_M0_inr_with_paise() -> None:
    assert inr(1234.5, decimals=2) == "₹1,234.50"
    assert inr(100000, decimals=2) == "₹1,00,000.00"
