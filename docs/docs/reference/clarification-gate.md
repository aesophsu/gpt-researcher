# Clarification Gate Protocol

GPT Researcher supports a blocking clarification gate during the `subqueries` stage.

## Enable

```bash
ENABLE_CLARIFICATION_GATE=true
```

Default is `false`.

## WebSocket events

### Server -> Client: `clarification_request`

```json
{
  "type": "clarification_request",
  "request_id": "b1453f0b5b5d4c1ab9c13e4f7ea0b8e0",
  "stage": "subqueries",
  "query": "user query",
  "generated_subqueries": ["...", "..."],
  "clarification_questions": ["...", "..."],
  "defaults": {
    "scope": null,
    "time_window": null,
    "language": null,
    "output_preference": null
  }
}
```

### Client -> Server: `clarification_response`

Prefix message with `clarification_response `:

```text
clarification_response {"request_id":"...","approved_subqueries":["..."],"constraints":{"scope":null,"time_window":null,"language":null,"output_preference":null},"notes":null}
```

Payload requirements:

- `approved_subqueries` must contain `1..10` non-empty entries.
- Entries are trimmed and de-duplicated server-side.

## Behavior

- Research pauses after `subqueries` generation and waits for clarification.
- Timeout is 5 minutes.
- On timeout, research is cancelled and an error event is emitted.
- `scope` is merged into `query_domains` when domain-like values are provided.
- `time_window` is stored as a constraint hint; retriever enforcement depends on provider support.
