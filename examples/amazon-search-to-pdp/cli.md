# Amazon via `dtwb`

**Recommended starting path:** Node **22.12+**, Python **3.11+** for local ASIN
selection, and `jq` for inspecting JSON. These are POSIX-shell examples from the
repository root, not an unattended batch. Ask before installing software and
agree on **one search page + one selected PDP** before submitting work.

```sh
npm install --global @datawebot/cli@0.1.1
dtwb --version
```

The [public CLI](https://github.com/datawebot/datawebot-cli) is a 0.x preview.
Installation does not grant Jobs access. Read [polling](../../guides/polling.md).
CLI progress/errors go to stderr; stdout is JSON on success. Do not mix the two.
Inspect exit codes before proceeding: 0 means a successful read/accepted request,
2 means partial results or invalid input, 1 means failure. Check `status` too.

## 1. Authenticate and discover

```sh
dtwb register you@example.com
umask 077
mkdir -p work
dtwb discover amazon > work/blueprints.json
```

Approve the code shown by the CLI using your email/website. Never paste a key
or approval token into chat. Existing valid sign-in is reused. Inspect the saved
catalog for `amazon.search_items` and `amazon.product_details`, their versions,
input schemas, supported markets and ENABLED availability. Stop on access denial
or maintenance; another registration is not a workaround.

## 2. Persist search intent, then submit once

Choose the authorized keyword/marketplace. A keyword alone defaults to amazon.com;
use a full URL for Singapore or another supported market. This template uses
Singapore but **must be edited to the user's approved input** before running:

```sh
python3 - <<'PY'
import json
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4
keyword = 'REPLACE_WITH_APPROVED_KEYWORD'
assert not keyword.startswith('REPLACE_'), 'Set the approved keyword first'
intent = {
    'blueprint_id': 'amazon.search_items',
    'url': 'https://www.amazon.sg/s?' + urlencode({'k': keyword}),
    'parameters': {'max_pages': 1},
    'idempotency_key': str(uuid4()),
}
with Path('work/search-intent.json').open('x') as f:
    json.dump(intent, f)
PY
```

Keep the intent and catalog private. The exclusive create deliberately refuses
to replace an earlier identity. Do not regenerate the key after a timeout.

```sh
# Submission only. Inspect success and retain job_id before waiting.
dtwb extract --async "$(jq -er '.blueprint_id' work/search-intent.json)" \
  "$(jq -er '.url' work/search-intent.json)" \
  --parameters "$(jq -c '.parameters' work/search-intent.json)" \
  --idempotency-key "$(jq -er '.idempotency_key' work/search-intent.json)" \
  > work/search-accepted.json
```

Inspect the exit code and acceptance JSON. Save `job_id` immediately; stderr also
contains it. A terminal FAILED/UNAVAILABLE acceptance is not a new retry task.
For a pending or completed accepted Job:

```sh
job_id=$(jq -er '.job_id' work/search-accepted.json)
dtwb retrieve "$job_id" --wait --page-size 100 > work/search-page1.json
```

`retrieve --wait` honors ETA, poll guidance and Retry-After. Timeout/Ctrl-C stops
waiting, not the server Job: retain the ID and repeat **retrieve**, not extract.
Unknown submission outcome with no ID? Inspect stderr/acceptance first, then
intentionally replay only the saved intent/key. The CLI resolves the live
blueprint version on submission: compare it with the saved catalog before replay;
stop on a version change or idempotency conflict. Use the [API checkpoint runner](api.md)
if you need automatic persistence/replay of the exact versioned API payload.

Synchronous `extract` can also submit/wait/retrieve one page, but it is an
alternative—not another submission to run after this sequence.

## 3. Retrieve every page, then collect ASINs locally

Continue only after COMPLETED. Inspect `errors` and `next_cursor` in the saved
page. PARTIAL_COMPLETE needs user review before any PDP fan-out. A CLI document
is **one API page**, not a full merged result set.

If `next_cursor` is non-null, copy it opaquely into the next read with the same
page size. Save successive pages under distinct names; repeat until null:

```sh
dtwb retrieve "$job_id" --page-size 100 --cursor 'OPAQUE_NEXT_CURSOR' \
  > work/search-page2.json
```

Pass **all pages explicitly in retrieval order**, including just page 1 when it
was the last page. Do not use a wildcard: page 10 can sort before page 2, and old
files from a different run can be mixed in.

```sh
python3 examples/amazon-search-to-pdp/select_asins.py work/search-page1.json \
  > work/asins.json
# If there were two pages, instead pass both files, page1 then page2.
```

The local helper checks complete ordered pages, deduplicates ASINs without
sorting them, and retains observed URLs/marketplaces. It submits nothing.
Inspect titles/fields in the original search pages and select **one relevant
candidate** from `work/asins.json`. The first result is not guaranteed relevant.
No candidates means no PDP, not an invented ASIN.

## 4. Submit one selected PDP

After choosing an observed URL and checking authorization, persist a separate
intent/key. Replace the placeholder; keep the exact marketplace/ASIN from search:

```sh
python3 - <<'PY'
import json
from pathlib import Path
from uuid import uuid4
url = 'REPLACE_WITH_SELECTED_OBSERVED_HTTPS_PRODUCT_URL'
assert not url.startswith('REPLACE_'), 'Select an observed product URL first'
candidates = json.loads(Path('work/asins.json').read_text())
assert any(item['url'] == url for item in candidates), 'URL must come from search'
with Path('work/pdp-intent.json').open('x') as f:
    json.dump({'blueprint_id': 'amazon.product_details', 'url': url,
               'parameters': {}, 'idempotency_key': str(uuid4())}, f)
PY

dtwb extract --async "$(jq -er '.blueprint_id' work/pdp-intent.json)" \
  "$(jq -er '.url' work/pdp-intent.json)" \
  --parameters "$(jq -c '.parameters' work/pdp-intent.json)" \
  --idempotency-key "$(jq -er '.idempotency_key' work/pdp-intent.json)" \
  > work/pdp-accepted.json
```

Inspect acceptance/exit code before retrieving:

```sh
pdp_id=$(jq -er '.job_id' work/pdp-accepted.json)
dtwb retrieve "$pdp_id" --wait --page-size 100 > work/pdp-page1.json
```

Follow any additional cursor with the same page size. Additional selected PDPs
are new source work requiring approved scope and separate identities—not polling.
Do not run a loop over every ASIN by default.

## 5. Report the observation, not a guarantee

Verify returned PDP ASIN/URL matches the selection. Include keyword/marketplace,
search/PDP Job IDs, source URL, as-of values and missing/partial/error fields.
Keep raw JSON privately. Search relevance, categories and field completeness
need inspection even when status is COMPLETED. Null is unknown, not zero.

A separate live CLI 0.1.0 report supports the bounded search→PDP workflow, not
this exact asynchronous sequence or all markets. See [verification notes](../../guides/verification.md).
