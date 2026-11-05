from pybrowser.search import find_all

def test_find_all_is_case_insensitive_and_non_overlapping():
    matches=find_all("Alpha alpha ALPHA", "alpha")
    assert [(m.start,m.end) for m in matches]==[(0,5),(6,11),(12,17)]

def test_find_all_empty_query():
    assert find_all("anything", "")==()

def test_find_all_unicode_casefold():
    assert len(find_all("Python PYTHON", "python"))==2
