"""Stage 7 — context builder (fixed window + topic segmentation + reply chains)."""
import datetime as dt

from aiwip_core import models as m
from aiwip_worker import context

BASE = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)


def _chat(db, ext):
    c = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=ext)
    db.add(c)
    db.flush()
    return c


def _msg(db, chat, ext, minutes, text="msg", reply_to=None, sender="u"):
    raw = {"id": ext}
    if reply_to is not None:
        raw["reply_to"] = reply_to
    msg = m.Message(
        chat_id=chat.id, external_message_id=ext, message_type=m.MessageType.text,
        text_content=text, normalized_content=text, sender_username=sender,
        sent_at=BASE + dt.timedelta(minutes=minutes), raw_payload=raw,
        processing_status=m.MessageProcessingStatus.normalized,
    )
    db.add(msg)
    db.flush()
    return msg


def test_last_20_window(db):
    chat = _chat(db, 800)
    for i in range(1, 26):  # 25 same-topic messages, 1 min apart
        _msg(db, chat, i, minutes=i)
    ctx = context.build_context(db, chat.id, window=20)
    assert len(ctx.messages) == 20
    assert ctx.messages[-1].external_message_id == 25
    assert ctx.messages[0].external_message_id == 6


def test_new_topic_split(db):
    chat = _chat(db, 801)
    _msg(db, chat, 1, minutes=0)      # old topic
    _msg(db, chat, 2, minutes=120)    # +2h → topic boundary
    _msg(db, chat, 3, minutes=125)
    _msg(db, chat, 4, minutes=130)
    ids = [cm.external_message_id for cm in context.build_context(db, chat.id).messages]
    assert 1 not in ids
    assert ids == [2, 3, 4]


def test_topic_continuation(db):
    chat = _chat(db, 802)
    for i in range(1, 6):
        _msg(db, chat, i, minutes=i * 5)  # within the gap
    ids = [cm.external_message_id for cm in context.build_context(db, chat.id).messages]
    assert ids == [1, 2, 3, 4, 5]


def test_reply_chain_pulls_referenced(db):
    chat = _chat(db, 803)
    _msg(db, chat, 1, minutes=0, text="root")    # old, outside the recent topic
    _msg(db, chat, 10, minutes=200)
    _msg(db, chat, 11, minutes=205)
    _msg(db, chat, 12, minutes=210, reply_to=1)  # replies to the old root
    ids = [cm.external_message_id for cm in context.build_context(db, chat.id).messages]
    assert set(ids) == {1, 10, 11, 12}  # root pulled in via reply reference


def test_confidence_in_range_and_grows_with_window(db):
    chat = _chat(db, 804)
    _msg(db, chat, 1, minutes=0)
    one = context.build_context(db, chat.id)
    assert 0.0 <= one.confidence <= 1.0
    for i in range(2, 12):
        _msg(db, chat, i, minutes=i)
    many = context.build_context(db, chat.id)
    assert 0.0 <= many.confidence <= 1.0
    assert many.confidence > one.confidence
