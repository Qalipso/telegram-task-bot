"""Stage 5 — message normalization (real Postgres)."""
from aiwip_core import models as m
from aiwip_worker import normalize


def _chat(db, ext):
    c = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=ext)
    db.add(c)
    db.flush()
    return c


def _msg(db, chat, ext, text=None, mtype=m.MessageType.text):
    msg = m.Message(
        chat_id=chat.id, external_message_id=ext, message_type=mtype,
        text_content=text, processing_status=m.MessageProcessingStatus.new,
    )
    db.add(msg)
    db.flush()
    return msg


def test_text_is_cleaned_and_normalized(db):
    msg = _msg(db, _chat(db, 700), 1, text="  Hello   world \n\n   foo  ")
    normalize.normalize_message(db, msg)
    assert msg.normalized_content == "Hello world\nfoo"
    assert msg.processing_status == m.MessageProcessingStatus.normalized


def test_empty_message_is_skipped(db):
    msg = _msg(db, _chat(db, 701), 1, text=None)
    normalize.normalize_message(db, msg)
    assert msg.normalized_content is None
    assert msg.processing_status == m.MessageProcessingStatus.skipped


def test_image_attachment_registered(db):
    chat = _chat(db, 702)
    msg = _msg(db, chat, 1, text=None, mtype=m.MessageType.image)
    db.add(m.MessageAttachment(message_id=msg.id, attachment_type=m.AttachmentType.image, processing_status=m.AttachmentProcessingStatus.new))
    db.flush()
    db.refresh(msg)
    normalize.normalize_message(db, msg)
    assert msg.processing_status == m.MessageProcessingStatus.normalized  # supported placeholder
    assert msg.attachments[0].processing_status == m.AttachmentProcessingStatus.new


def test_unsupported_document_marked_skipped_without_breaking(db):
    chat = _chat(db, 703)
    msg = _msg(db, chat, 1, text=None, mtype=m.MessageType.document)
    db.add(m.MessageAttachment(message_id=msg.id, attachment_type=m.AttachmentType.document, mime_type="application/x-rar", processing_status=m.AttachmentProcessingStatus.new))
    db.flush()
    db.refresh(msg)
    normalize.normalize_message(db, msg)
    assert msg.attachments[0].processing_status == m.AttachmentProcessingStatus.skipped
    assert msg.processing_status == m.MessageProcessingStatus.skipped  # no text, only unsupported file


def test_supported_document_normalized(db):
    chat = _chat(db, 704)
    msg = _msg(db, chat, 1, text="see attached", mtype=m.MessageType.document)
    db.add(m.MessageAttachment(message_id=msg.id, attachment_type=m.AttachmentType.document, mime_type="application/pdf", processing_status=m.AttachmentProcessingStatus.new))
    db.flush()
    db.refresh(msg)
    normalize.normalize_message(db, msg)
    assert msg.processing_status == m.MessageProcessingStatus.normalized
    assert msg.attachments[0].processing_status == m.AttachmentProcessingStatus.new


def test_normalize_pending_batch(db):
    chat = _chat(db, 705)
    _msg(db, chat, 1, text="hi")
    _msg(db, chat, 2, text="yo")
    assert normalize.normalize_pending(db) == 2
    statuses = [mm.processing_status for mm in db.query(m.Message).filter_by(chat_id=chat.id).all()]
    assert all(s == m.MessageProcessingStatus.normalized for s in statuses)
