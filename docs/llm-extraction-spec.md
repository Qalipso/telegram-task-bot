# LLM Extraction Specification

> Document 5 of the **AI Work Intelligence Platform** documentation set.
> This is the canonical English version (`llm-extraction-spec.md`); a maintained Russian copy lives in `llm-extraction-spec.ru.md`.

## Purpose

The LLM pipeline must analyze stored messages and create structured Work Item
Candidates. The system **does not create final Work Items automatically** — every detected item
goes through human approval.

## Input

The LLM receives a Context Window from the database. The Context Window includes:

- new messages
- previous messages, if they relate to the same topic
- reply chain
- quoted messages
- metadata about authors
- the current date and time in UTC
- the list of available assignees
- the list of aliases

## Output

The LLM must return structured JSON.

Root object:

```json
{
  "candidates": [],
  "context_summary": "",
  "context_confidence": 0
}
```

### Candidate Schema

```json
{
  "type": "task",
  "title": "",
  "summary": "",
  "priority": "medium",
  "due_date": null,
  "assignees": [],
  "source_message_ids": [],
  "supporting_message_ids": [],
  "reasoning_summary": "",
  "missing_fields": [],
  "confidence": {
    "item": 0,
    "context": 0,
    "assignee": 0,
    "priority": 0,
    "due_date": 0
  }
}
```

### Candidate Types

```text
task
request
reminder
idea
knowledge
```

Future placeholders: `decision`, `risk`.

### Priority Values

```text
critical
high
medium
low
null
```

Rules:

- If the priority is stated explicitly, use the stated value.
- If the priority is not stated, the model may determine it on its own.
- If there is not enough information, return null.
- Use critical only in cases of explicit urgency, a blocker, a risk of failure, or a business-critical
  action.

### Assignee Rules

- Assignees are chosen only from the finite list of assignees.
- Multiple assignees may be selected.
- If no assignee can be determined, the candidate is marked as requiring review.
- If there are several possible assignees, return the options with confidence.
- Do not create a new assignee automatically.
- The message author may be an assignee only if the context explicitly indicates this.

### Due Date Rules

- Use the current date and time in UTC.
- Convert relative dates into a calendar date.
- Return ambiguous dates with low confidence.
- If no deadline can be determined, `due_date = null`.
- If `due_date = null`, the candidate is still created.

### Context Rules

- Analyze a window of messages, not a single message.
- Use the last 20 messages from the database.
- If the topic is continuing, take the preceding context into account.
- If a new topic has started, do not mix it with the previous one.
- For task recognition, precision matters more than completeness.
- False tasks are worse than missed weak signals.

### Confidence Rules

```text
item_confidence > 0.90 = strong candidate
0.70–0.90 = candidate requires review
< 0.70 = usually skip or mark low confidence
```

Target metrics:

```text
Task Recognition > 90%
Context Understanding > 80%
```

### Missing Fields

Possible values: `assignee`, `priority`, `due_date`, `context`, `source`.

If a required field is missing, the UI must highlight the candidate.

## AI Run Logging

For each run, store:

```text
model_provider
model_name
prompt_version
input_payload
output_payload
tokens_input
tokens_output
cost
status
error_message
```

## Error Handling

If the LLM returns invalid JSON:

- save the AI run as failed
- do not break the entire sync
- mark the batch as `partial_success`
- allow a retry

If the confidence is low:

- do not create a WorkItem
- create a Candidate only if there is useful information
- mark it `needs_review`

## Human Feedback Loop

After review, store:

```text
approved
rejected
edited_then_approved
```

This data is used for the Evaluation Dataset.
