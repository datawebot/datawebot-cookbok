# Amazon search → ASINs → product details

**User problem:** “Find products matching my keyword, collect their ASINs, and
inspect a small selection in more detail.”

**Suggested starting scope:** one search page, then one selected PDP Job.
Expanding to every ASIN is new source work, not an automatic continuation.

## Choose one path

- [CLI recipe](cli.md): recommended starting point for an agent/operator with
  a shell. Public npm installation, email-approved sign-in and saved JSON pages.
- [Python API recipe](api.md): runnable standard-library client with a durable
  per-Job checkpoint, polling and full result pagination. Use when you already
  have an approved customer API key.
- [MCP recipe](mcp.md): tool-call walkthrough for an already connected agent.
  No script installation needed.

## Outcome

1. Discover `amazon.search_items` and `amazon.product_details`.
2. Submit one search URL with `max_pages: 1`.
3. Wait near ETA; poll metadata by the returned guidance, not in a tight loop.
4. Retrieve all result pages and deduplicate ASINs in record order.
5. Select relevant ASINs using the user’s criteria. Preserve their returned URLs
   and marketplace; do not invent ASINs or change country silently.
6. Submit one PDP per authorized selected URL, each with its own stable key.
7. Retrieve and summarize observed details with Job IDs and as-of information.

Search and PDP are different source observations. A changed price, missing
field or empty result is not proof the script failed. A completed search does
not guarantee relevant products, clean categories or complete fields. Inspect
titles, prices/currency and nulls; don't blindly enrich the first returned ASIN.
Report uncertainty and never call a result guaranteed-current. A PARTIAL_COMPLETE search needs review
before any PDP fan-out; FAILED/UNAVAILABLE does not retry itself.

Read [polling and recovery](../../guides/polling.md) first. Included test data is
synthetic. A separate live CLI acceptance report supports the bounded workflow,
not every script or field; see [verification notes](../../guides/verification.md).
