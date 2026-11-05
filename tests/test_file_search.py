from pybrowser.file_search import compile_pattern, find_hits


def test_find_hits_reports_line_column_and_preview():
    hits = find_hits("alpha\nbeta alpha\n", "alpha")
    assert [(hit.line, hit.column) for hit in hits] == [(1, 1), (2, 6)]
    assert hits[1].preview == "beta alpha"


def test_find_hits_case_and_whole_word():
    assert len(find_hits("Path path pathlib", "path")) == 3
    assert len(find_hits("Path path pathlib", "path", match_case=True)) == 2
    assert len(find_hits("Path path pathlib", "path", whole_word=True)) == 2


def test_replace_pattern_literal_and_case_insensitive():
    pattern = compile_pattern("a.b", match_case=False)
    assert pattern.sub("x", "A.B a.b") == "x x"
