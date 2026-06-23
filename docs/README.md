# AI Work Intelligence Platform — Documentation

> This is the canonical English version (`README.md`); the maintained Russian copy lives in `README.ru.md`.
> Language convention (D7): **EN is canonical** (`*.md`), RU is the maintained copy (`*.ru.md`).

A documentation set that turns work discussions from Telegram into structured Work Items
through human-in-the-loop review.

All documents are flat files in `docs/`: every document is `docs/<name>.md` (canonical English)
plus `docs/<name>.ru.md` (the maintained Russian copy). There are no `en/` or `ru/` subdirectories.

| # | Document | File (EN / RU) |
|---|----------|----------------|
| ★ | Final System Specification v1.0 (authoritative) | `system-spec.md` / `system-spec.ru.md` |
| 1 | Product Brief | `product-brief.md` / `product-brief.ru.md` |
| 2 | Domain Model | `domain-model.md` / `domain-model.ru.md` |
| 3 | Technical Architecture Overview | `architecture.md` / `architecture.ru.md` |
| 4 | Database Design | `database-design.md` / `database-design.ru.md` |
| 5 | LLM Extraction Specification | `llm-extraction-spec.md` / `llm-extraction-spec.ru.md` |
| 6 | Evaluation Plan | `evaluation-plan.md` / `evaluation-plan.ru.md` |
| 7 | Test Plan (110 cases) | `test-plan.md` / `test-plan.ru.md` |
| — | Design Decisions | `decisions.md` / `decisions.ru.md` |
| — | Reconciliation Report | `reconciliation.md` / `reconciliation.ru.md` |

**History:** the former "Telegram Task Recognition Bot" design spec (`docs/specs/2026-06-23-…`)
has been merged into this set and retired (see `decisions.md`).
