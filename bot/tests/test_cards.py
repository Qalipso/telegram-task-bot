"""Phase 4 — card rendering (text body + keyboard)."""
from aiwip_bot import cards


def _cand(**over):
    base = {
        "id": 7,
        "candidate_type": "task",
        "title": "Ship the Q3 report",
        "summary": "Send the finished report to finance.",
        "priority": "high",
        "due_date": "2026-07-03T00:00:00+00:00",
        "status": "new",
        "task_confidence": 0.95,
        "assignee_confidence": 0.9,
        "priority_confidence": 0.7,
        "due_date_confidence": 0.8,
        "context_confidence": 0.8,
        "missing_fields": [],
        "assignee_count": 1,
        "assignee_ambiguous": False,
        "unresolved_mentions": None,
    }
    base.update(over)
    return base


def test_text_includes_title_and_id():
    text = cards.format_candidate_text(_cand())
    assert "Ship the Q3 report" in text
    assert "#7" in text  # candidate id is visible for traceability


def test_long_title_is_truncated():
    text = cards.format_candidate_text(_cand(title="x" * 400))
    assert "x" * 400 not in text
    assert "…" in text


def test_missing_fields_render_as_badge():
    text = cards.format_candidate_text(_cand(status="needs_review", missing_fields=["assignee", "due_date"]))
    assert "ответственный" in text and "срок" in text  # human labels, not raw field names


def test_ambiguous_assignee_shows_unresolved_mention():
    text = cards.format_candidate_text(
        _cand(status="needs_review", assignee_count=0, assignee_ambiguous=True,
              unresolved_mentions=["Саша"])
    )
    assert "Саша" in text


def _btn_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def _btn_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_ready_card_has_approve_reject_assign():
    markup = cards.build_keyboard(_cand(status="new", missing_fields=[], assignee_count=1))
    texts = _btn_texts(markup)
    assert any("Одобрить" in t for t in texts)
    assert any("Отклонить" in t for t in texts)


def test_no_approve_all_button_ever():
    markup = cards.build_keyboard(_cand(status="new", missing_fields=[], assignee_count=1))
    texts = _btn_texts(markup)
    assert not any("all" in t.lower() for t in texts)


def test_needs_review_has_no_one_tap_approve():
    markup = cards.build_keyboard(_cand(status="needs_review", missing_fields=["due_date"], assignee_count=1))
    texts = _btn_texts(markup)
    assert not any(t.strip() in ("Одобрить", "✅ Одобрить") for t in texts)
    assert any("Отклонить" in t for t in texts)


def test_ambiguous_assignee_offers_who():
    markup = cards.build_keyboard(_cand(status="needs_review", assignee_count=0, assignee_ambiguous=True))
    texts = _btn_texts(markup)
    assert any("Кто" in t for t in texts)


def test_unassigned_offers_assign():
    markup = cards.build_keyboard(_cand(status="needs_review", missing_fields=["assignee"], assignee_count=0))
    texts = _btn_texts(markup)
    assert any("Назначить" in t for t in texts)


def test_callback_data_carries_candidate_id():
    markup = cards.build_keyboard(_cand(id=42, status="new", missing_fields=[], assignee_count=1))
    assert all("42" in d for d in _btn_data(markup))


def test_render_card_bundles_text_and_keyboard():
    card = cards.render_card(_cand(id=5, status="new", missing_fields=[], assignee_count=1))
    assert card.candidate_id == 5
    assert "#5" in card.text
    assert any("Одобрить" in b.text for row in card.reply_markup.inline_keyboard for b in row)


def test_card_shows_resolved_assignee_name():
    text = cards.format_candidate_text(_cand(status="new", assignee_count=1, assignees=["Иван"]))
    assert "Иван" in text


def test_card_assignee_line_lists_multiple_names():
    text = cards.format_candidate_text(_cand(status="new", assignee_count=2, assignees=["Иван", "Эдуард"]))
    assert "Иван" in text and "Эдуард" in text
