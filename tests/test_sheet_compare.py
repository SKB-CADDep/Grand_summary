from src.services.sheet_compare import combine_compare_targets, values_differ


def test_combine_or_unions_checked_tabs_and_range():
    ids = ["main", "base", "a", "b", "c"]
    assert combine_compare_targets(ids, "main", ["a"], "b", "c", "or") == ["a", "b", "c"]


def test_combine_always_unions_checked_tabs_and_range():
    ids = ["main", "base", "a", "b", "c"]
    assert combine_compare_targets(ids, "main", ["a", "b"], "b", "c", "and") == ["a", "b", "c"]


def test_range_only_skips_current_tab():
    ids = ["main", "base", "a"]
    assert combine_compare_targets(ids, "main", [], "main", "a", "or") == ["base", "a"]


def test_checked_only_when_range_empty():
    ids = ["main", "base", "a"]
    assert combine_compare_targets(ids, "a", ["main", "missing"], None, None, "and") == ["main"]


def test_values_differ_treats_empty_as_equal():
    assert values_differ(None, "") is False
    assert values_differ("120", "130") is True
