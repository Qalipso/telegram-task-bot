"""Stage 5 — message normalization.

Text → cleaned `normalized_content`; attachments registered as placeholders (no media
intelligence yet — system-spec §9/§10); unsupported attachments are marked `skipped` and do
NOT break processing. Updates `messages.processing_status`.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_core.logging import get_logger
from aiwip_core.models import (
    AttachmentProcessingStatus,
    AttachmentType,
    Message,
    MessageAttachment,
    MessageProcessingStatus,
)

logger = get_logger("aiwip.worker.normalize")

# Documents we can extract text from later (system-spec §9); others are registered but skipped.
SUPPORTED_DOC_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
}

_WS = re.compile(r"[ \t]+")


def clean_text(text: str) -> str:
    lines = [_WS.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _attachment_supported(att: MessageAttachment) -> bool:
    # image/voice are registered placeholders for future OCR/vision/transcription.
    if att.attachment_type in (AttachmentType.image, AttachmentType.voice):
        return True
    if att.attachment_type == AttachmentType.document:
        return att.mime_type in SUPPORTED_DOC_MIMES
    return False


def normalize_message(db: Session, message: Message) -> Message:
    normalized = clean_text(message.text_content) if message.text_content else ""
    message.normalized_content = normalized or None
    has_usable_content = bool(normalized)

    for att in message.attachments:
        if _attachment_supported(att):
            has_usable_content = True  # leave att.processing_status='new' as a placeholder
        else:
            att.processing_status = AttachmentProcessingStatus.skipped

    message.processing_status = (
        MessageProcessingStatus.normalized if has_usable_content else MessageProcessingStatus.skipped
    )
    return message


def normalize_pending(db: Session, limit: int = 500) -> int:
    pending = db.execute(
        select(Message).where(Message.processing_status == MessageProcessingStatus.new).limit(limit)
    ).scalars().all()
    for message in pending:
        try:
            normalize_message(db, message)
        except Exception as exc:  # noqa: BLE001 — one bad message must not break the batch
            logger.warning("normalize failed message=%s: %s", message.id, exc)
            message.processing_status = MessageProcessingStatus.failed
    db.commit()
    logger.info("normalized %s message(s)", len(pending))
    return len(pending)
