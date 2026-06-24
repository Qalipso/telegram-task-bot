"""Dry-run the extraction prompt against a chat's current context window.

Builds the same context the live pipeline would, calls the LLM, and prints the candidates it
returns — WITHOUT writing anything to the database. Use it to validate prompt/recall changes
against real messages without creating duplicate candidates.

Run inside the worker container (has OPENAI_API_KEY + DB access):
    docker cp scripts/extract_dryrun.py aiwip-worker-1:/tmp/dryrun.py
    docker exec aiwip-worker-1 python /tmp/dryrun.py            # default internal chat id = 1
    docker exec aiwip-worker-1 python /tmp/dryrun.py 1
"""
from __future__ import annotations

import datetime as dt
import sys

from sqlalchemy import select

from aiwip_core.db import get_sessionmaker
from aiwip_core.models import Assignee
from aiwip_worker import context as ctxmod
from aiwip_worker.llm import prompts
from aiwip_worker.llm import schema as llm_schema
from aiwip_worker.llm.client import OpenAIClient


def main() -> None:
    chat_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    with get_sessionmaker()() as db:
        ctx = ctxmod.build_context(db, chat_id)
        print(f"prompt_version={prompts.PROMPT_VERSION}  chat_id={chat_id}  window={len(ctx.messages)} msg(s)")
        for m in ctx.messages:
            print(f"  [{m.external_message_id}] @{m.sender or '?'}: {m.text!r}")
        if not ctx.messages:
            print("empty window — nothing to extract")
            return

        assignees = db.execute(select(Assignee).where(Assignee.is_active.is_(True))).scalars().all()
        system, user = prompts.build_messages(ctx, assignees, dt.datetime.now(dt.timezone.utc))
        res = OpenAIClient().extract(system, user, prompts.JSON_SCHEMA)
        print(f"\nLLM status={res.status} model={res.model} tokens={res.tokens_input}->{res.tokens_output}")
        if res.status != "success" or res.output is None:
            print(f"error: {res.error}")
            return

        parsed = llm_schema.LLMOutput.model_validate(res.output)
        print(f"context_summary: {parsed.context_summary}")
        print(f"candidates returned: {len(parsed.candidates)}")
        for c in parsed.candidates:
            band = "new" if c.confidence.item >= 0.90 else ("needs_review" if c.confidence.item >= 0.60 else "SKIPPED")
            print(
                f"  * [{c.type}] {c.title!r} prio={c.priority} item={c.confidence.item:.2f} "
                f"-> {band} | assignees={c.assignees} missing={c.missing_fields}"
            )


if __name__ == "__main__":
    main()
