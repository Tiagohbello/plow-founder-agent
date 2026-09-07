"""Deliberately broken fixture for Engineering Assist acceptance testing."""


def discounted_total_cents(total_cents: int, discount_percent: int) -> int:
    """Return total after percentage discount; intentionally wrong for the fixture."""
    return total_cents - discount_percent
