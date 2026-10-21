# Resume a Job without extracting again

**User problem:** “The agent timed out, my shell closed, or I came back later.
Can I read the result without creating another Job?”

Yes: retain the original identity. Polling and retrieval are read-only. A local
timeout did not cancel server work. Read [the polling guide](../../guides/polling.md).

## API (runnable)

If you used the [API recipe](../amazon-search-to-pdp/api.md), keep the same
private checkpoint, API origin and authorized account/key:

```sh
python3 examples/amazon-search-to-pdp/api.py --state work/search-state.json \
  > work/search-results.json
```

- A saved `job_id` means this performs GET-only status/results reads.
- If the POST outcome was unknown and no ID was saved, it deliberately replays
  the stored exact payload and same idempotency key; no new key is generated.
- A changed origin/request is refused instead of overwriting the checkpoint.
- FAILED/PARTIAL_COMPLETE/UNAVAILABLE remain terminal; no source retry.
- If you have only an ID, use your approved HTTP client for `GET /v1/jobs/ID`,
  then the result endpoint/cursors after terminal status. Do not invent a new
  request/checkpoint as a way to recover a known Job.

## MCP

Call `get_job {job_id: "SAVED_ID"}` on the customer MCP gateway. If pending,
wait according to ETA/poll guidance before another read. For COMPLETED,
PARTIAL_COMPLETE or FAILED, call `get_results {job_id: "SAVED_ID", page_size: 100}`
and follow `next_cursor`. UNAVAILABLE is maintenance: stop without result retrieval.
Use the current discovered schema; check protocol/tool errors, not just HTTP 200.
A chat-only agent without a wait facility should report next-read time, not
promise a background task it cannot schedule. **Do not call submit_job.**

## CLI

```sh
dtwb status SAVED_JOB_UUID
dtwb retrieve SAVED_JOB_UUID --wait > work/resumed-page1.json
# Follow any result next_cursor with the same page size.
```

Do not run `extract` again for a known ID. Install the public `@datawebot/cli@0.1.1`
with Node 22.12+ as shown in the [CLI recipe](../amazon-search-to-pdp/cli.md), or
use API/MCP. If you've lost the ID, `dtwb jobs` lists your account's Jobs; inspect
request metadata to identify the original, rather than submitting replacement work.

## What stops recovery?

- 401: get approved access through normal onboarding; never guess another key.
- 403: eligibility/permissions; do not repeat sign-in or bypass the gate.
- 404: wrong ID/account, missing or unavailable endpoint; inspect, do not replace.
- 410: retained results expired (currently seven days); ask before a fresh run.
- Invalid/repeated cursor or inconsistent record identity: stop and preserve data.

A fresh user-authorized execution can be a separate decision after diagnosing a
terminal failure/expiry. Do not label it “resuming” the original Job.
