"""Tests for the text helpers of the dialogue executor."""

from agent_oak.executor.dialogue import _continues, _is_page, join_texts


def test_is_page_rejects_menus_drawn_over_the_box() -> None:
    """Rows of a menu box are not a page of text."""
    assert _is_page(["Enemy CATERPIE", "used STRING SHOT!"])
    assert not _is_page([])
    assert not _is_page(["│", "│▶FIGHT <PK><MN>", "│", "│ ITEM  RUN"])


def test_continues_while_letters_are_printed() -> None:
    """A page that is still printing continues the last one, a new one not."""
    assert _continues(["SQUIRTLE"], ["SQUIRTLE", "used"])
    assert _continues(["SQUIRTLE", "used"], ["SQUIRTLE", "used TACKLE!"])
    assert not _continues(["Enemy CATERPIE", "used STRING SHOT!"], ["B"])
    assert not _continues(["A", "B"], ["B"])  # scrolled up one line


def test_join_texts_drops_overlap() -> None:
    """A page read by two consecutive calls is only kept once."""
    assert join_texts(["A\nB", "B\nC"]) == "A\nB\nC"
