# Polling: submit once, wait intelligently, retrieve without resubmitting

This is the shared lifecycle for extraction Jobs through API, MCP and `dtwb`.
A status read does not start source work. A result read does not retry a scrape.

## 1. Discover and authorize

Read the current blueprint's input/record schemas, supported marketplaces,
version, maintenance state and limits. Ask the user to authorize scope. One Job
accepts **one URL**; multiple PDPs mean multiple intentional Jobs.

Authentication and blueprint eligibility are separate. A 403 or paused blueprint
is not a reason to sign in repeatedly or seek internal credentials. `credits`
currently reports synthetic/unbilled Jobs credits: do not invent monetary prices
or treat that balance as unlimited authorization.

## 2. Persist identity before submission

Save the API origin, **exact payload** and a fresh random idempotency key before
sending a Job. API: `Idempotency-Key` header (8–128 letters, digits, `_`, `-`).
MCP: `idempotency_key` argument. Save `job_id` as soon as accepted.

- Unknown POST outcome (network timeout/disconnect): replay the same payload with
  the **same key**, deliberately and with bounded attempts. Never choose a new
  key just to “try again.” Our API runner exits and resumes via the checkpoint;
  it does not automatically retry POST.
- Accepted Job: use its ID to read/wait/retrieve; do not POST it again.
- Same key + different payload is a conflict, not a mechanism to update a Job.
- Checkpoints contain request data/Job IDs, not API keys. Keep them private and
  out of Git. Run one process per state file.

## 3. Wait for the next useful read

For each PENDING/INITIATED metadata response:

```text
wait_seconds = max(
    2,
    seconds_until(eta_delivery),
    poll_after_seconds,
    Retry-After if exposed by the transport
)
sleep(wait_seconds, bounded by remaining wait budget)
read the SAME job_id's metadata
```

Use zero for absent/past ETA, default two seconds for missing poll guidance.
Reject malformed guidance rather than spinning. `Retry-After` may be seconds or
an HTTP date. Every status response can extend ETA; recompute from that response.
ETA is an estimate, **not a completion promise**. Do not poll each second while
ETA is a minute away, fetch result pages while still pending, or use a source
request as a health check.

Read-only requests may retry transient 429/502/503/504 with bounded backoff and
`Retry-After`. Preserve IDs throughout. Missing/invalid auth, access denial,
malformed input and idempotency conflicts are not blindly retryable.

**Default wait budget: ten minutes per Job**, including status/retrieval requests.
A timeout or Ctrl-C stops the client, not the server. Retain the ID/checkpoint
and [resume later](../examples/resume-job/README.md). Do not cancel or replace work
unless the API offers a documented cancellation operation and the user asks.

### Agents without a long-running wait tool

Do not fabricate a “sleep” MCP tool or keep calling `get_job` to make time pass.
Use your environment's real delayed/background task facility if available, or
return the Job ID, ETA and next eligible read time and ask the user to resume.
Do not promise a follow-up task that your environment cannot schedule.

## 4. Terminal states

| Status | Meaning / next action |
| --- | --- |
| PENDING / INITIATED | Metadata only. Wait before another status read. |
| COMPLETED | Retrieve all result pages. It does not promise a non-empty set or current prices. |
| PARTIAL_COMPLETE | Retrieve available pages **and errors**. Report incompleteness; ask before expanding/retrying. |
| FAILED | Terminal. Retrieve/report error details; no new extraction without a new user-authorized request. |
| UNAVAILABLE | Maintenance; no source dispatch. Stop. Do not silently substitute a different tool. |

A terminal Job stays terminal. Polling it cannot turn failure into success.
The Python runner prints a labeled cookbook envelope `{ "job": ..., "pages": [...] }`,
not a fabricated raw API response. Each page inside is preserved. It exits 0 for
COMPLETED, 2 for PARTIAL_COMPLETE, 1 for other failures, 130 for Ctrl-C.

## 5. Retrieve every result page

API: `GET /v1/jobs/{id}/results?page_size=100[&cursor=...]`.
MCP gateway: `get_results {job_id,page_size:100,cursor?}`.
CLI: `dtwb retrieve ID --page-size 100 [--cursor ...]`.

Each record is `{ "record_index": 0, "data": { ... } }`; read the fields in
`data`. Validate them against the discovered record schema before downstream use.
Keep one page size throughout, pass `next_cursor` opaquely and URL-encoded until
null, and stop on repeated cursors, duplicate indices or mismatched Job IDs.
Do not confuse a result cursor with the separate account-history cursor.

Results currently have a seven-day public retention period. Follow the current
catalog; a 410 means expired results, not permission to rerun automatically.
Export authorized results before expiry and retain their Job IDs/as-of times.

## Transport differences

- **API:** `https://api.datawebot.com/v1/...`, customer bearer key. Status is
  `GET /v1/jobs/{id}`. Polling can observe HTTP `Retry-After` directly.
- **Customer MCP:** `https://mcp.datawebot.com/mcp`, connected through the user's
  client with its normal authentication. Discover first. Gateway names are
  `list_job_blueprints`, `submit_job`, `get_job`, **`get_results`**. Tool output
  is under `structuredContent`; check JSON-RPC errors and `isError`, even on HTTP
  200. Some clients surface only text content; parse that JSON rather than guessing.
  The gateway may not expose HTTP retry headers; use the timing/error guidance
  actually returned, or stop if rate-limit recovery cannot be determined.
- **CLI:** polling is handled by synchronous `extract` or `retrieve --wait`.
  `extract --async` just submits. Raw API JSON goes to stdout; progress to stderr.
  It returns one result page, not every page concatenated together.

These are not three separate systems. Never run the three recipe variants for
the same intent unless the user really wants separate extractions.
