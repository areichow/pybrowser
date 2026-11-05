from pybrowser.conventions import canonical_category, category_sort_key, display_scope

def test_smalltalk_display_conventions():
    assert display_scope("<module>") == "-- module --"
    assert canonical_category("Imports") == "-- imports --"
    assert canonical_category("Uncategorized") == "as yet unclassified"

def test_special_categories_sort_first_in_requested_order():
    values = ["jobs", "-- variables --", "-- docs --", "-- imports --", "as yet unclassified", "-- constants --", "-- functions --"]
    assert sorted(values, key=category_sort_key) == ["-- imports --", "-- constants --", "-- docs --", "-- functions --", "-- variables --", "jobs", "as yet unclassified"]
