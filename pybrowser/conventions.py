"""Smalltalk-style browser display conventions."""

SPECIAL_CATEGORY_ALIASES = {
    "documentation": "-- docs --",
    "docs": "-- docs --",
    "imports": "-- imports --",
    "constants": "-- constants --",
    "functions": "-- functions --",
    "variables": "-- variables --",
    "uncategorized": "as yet unclassified",
    "as yet unclassified": "as yet unclassified",
}

SPECIAL_CATEGORY_ORDER = {
    "-- imports --": 0,
    "-- constants --": 1,
    "-- docs --": 2,
    "-- functions --": 3,
    "-- variables --": 4,
}

MODULE_SCOPE = "<module>"
MODULE_SCOPE_DISPLAY = "-- module --"


def canonical_category(name: str) -> str:
    stripped = name.strip()
    return SPECIAL_CATEGORY_ALIASES.get(stripped.casefold(), stripped)


def category_sort_key(name: str):
    canonical = canonical_category(name)
    if canonical in SPECIAL_CATEGORY_ORDER:
        return (0, SPECIAL_CATEGORY_ORDER[canonical], "")
    if canonical == "as yet unclassified":
        return (2, 0, "")
    return (1, 0, canonical.casefold())


def display_scope(name: str) -> str:
    return MODULE_SCOPE_DISPLAY if name == MODULE_SCOPE else name


def is_special_category(name: str) -> bool:
    return canonical_category(name) in SPECIAL_CATEGORY_ORDER
