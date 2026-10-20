# Verification and data-quality notes

## What was checked

As of **2026-10-20**:

- This repository's Python tests run offline with synthetic records and fake or
  loopback HTTP. They cover identity checkpoints, polling, pagination, recovery,
  local ASIN selection and CSV output. They do not submit extraction Jobs.
- `@datawebot/cli@0.1.1` was independently installed from the public npm registry
  with an empty npm configuration/cache. Version/help, package integrity,
  license and runtime-source comparison passed. No sign-in/extraction was run
  during that package check.
- A separate operator supplied a **CLI 0.1.0 live acceptance report**, dated
  2026-10-20, from macOS with Node 22.23.3. It reports email-approved sign-in and
  resume, saved-key reuse, discovery, synthetic credits, account Job listing,
  status, retrieval and pagination passing.
- That report records exactly **three new extraction Jobs**: one Amazon Singapore
  search page for “electric bike”, then PDPs for the first two returned products.
  All three reached COMPLETED with empty error arrays. Search returned 48 records;
  each PDP returned one. The report says URL/ASIN matching and pagination assertions
  passed. No extra live extraction was performed for this cookbook.

The live report was reviewed, but its original JSON/log artifacts remain on the
operator's machine; they are not durable public evidence and were not independently
replayed here. Account identifiers, Job IDs, local evidence paths and raw customer
records are deliberately not copied into this public repository. This is a summary
of reported CLI acceptance, **not** a live test of the Python/MCP recipes, the exact
shell walkthrough, every market or CLI 0.1.1. The 0.1.1 follow-up changed public
release documentation/package checks, not CLI runtime behavior.

## What the live report warns us about

- **Relevance:** the first two “electric bike” results appeared to be ordinary
  folding bicycles. Preserve returned order, but inspect titles against the
  user's criteria before selecting PDPs. Search position is not a relevance guarantee.
- **Categories:** both PDPs had the same broad category path, apparently mixing
  unrelated navigation categories. Do not use category text as a verified taxonomy.
  Root cause was not investigated in the report.
- **Missing fields:** search ratings were null while PDP ratings were populated.
  Several optional PDP fields were also null. Missing is unknown, never zero.
- **Independent accuracy:** the report did not compare fields to a separate browser
  capture. COMPLETED describes Job execution, not verified source accuracy.
- **Billing:** the tested account explicitly reported synthetic/unbilled credits
  with debits disabled. No real charging or monetary balance was validated.

When reporting a new run, retain its source URLs, Job IDs, as-of values, scope,
partial/errors and limitations in the user's private workspace. Never claim this
reported sample guarantees current prices, clean categories, complete fields or
availability for another account. Discovery and current responses remain authoritative.
