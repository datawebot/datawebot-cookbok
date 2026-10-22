# datawebot cookbook

Practical, agent-readable recipes for solving ecommerce data problems with
[datawebot](https://www.datawebot.com). Use the API, MCP, or the `dtwb` CLI—pick
**one** path for a task, not all three (that would create duplicate work).

> Give your agent this repository or an individual recipe URL. Recipes explain
> what to ask, what to submit, when to wait, how to recover, and how to interpret
> results. They are not instructions to run source requests without your approval.

## What is datawebot?

datawebot gives AI agents ecommerce product data: product search across online shops
worldwide and seller offers with direct links to each shop, through an MCP server.

Learn more: [About datawebot](https://www.datawebot.com/about).

## Start here

1. Read [the agent instructions](AGENTS.md) and [the polling contract](guides/polling.md).
2. Set up your own access using [datawebot's agent setup](https://mcp.datawebot.com/setup.md)
   or the [MCP connection guide](https://github.com/datawebot/datawebot-mcp).
3. Discover the current tools/blueprints. Authentication does **not** guarantee
   access to every blueprint: preview eligibility, maintenance and limits still apply.
4. Agree on a bounded task. Start with one search page and **one** selected product.
5. Choose a recipe below. Save Job IDs and checkpoints; never create a new Job
   merely because a wait timed out.

## Recipes

| User problem | Recipe | Interface | Status |
| --- | --- | --- | --- |
| “Find products matching this Amazon keyword, collect ASINs, then inspect one product.” | [Amazon search → ASINs → PDP](examples/amazon-search-to-pdp/README.md) | [CLI](examples/amazon-search-to-pdp/cli.md), [Python API](examples/amazon-search-to-pdp/api.md), [MCP](examples/amazon-search-to-pdp/mcp.md) | Offline-tested scripts; related live CLI acceptance reported |
| “My agent stopped waiting. Can I get the result without running it again?” | [Resume an existing Job](examples/resume-job/README.md) | API, MCP, CLI | API reuses the tested checkpoint runner |
| “Put the records I already downloaded into a spreadsheet.” | [Saved results → CSV](examples/results-to-csv/README.md) | Local Python | Runnable; no network calls |
| “Compare shops' current offers and keep my own price history.” | [Existing Python price tracker](https://github.com/datawebot/datawebot-mcp/tree/main/examples/python-price-tracker) | MCP | Maintained in the MCP repo; not duplicated here |

The API examples require **Python 3.11+**, standard library only. No SDK,
framework, server deployment, npm publication or private infrastructure access.

### Use the CLI

The public [CLI](https://github.com/datawebot/datawebot-cli) is an initial 0.x
preview. With Node **22.12+**, install the verified npm release:

```sh
npm install --global @datawebot/cli@0.1.1
dtwb --version
dtwb --help
```

Then follow the [CLI recipe](examples/amazon-search-to-pdp/cli.md). Installation
and source access do not grant Jobs eligibility. Agents should ask before
installing software or submitting work.

### Evidence, not promises

These recipes were checked against the customer contract on **2026-10-20**.
Offline tests use explicitly synthetic records, never pretend-live output.
A separate operator report records bounded live acceptance of CLI **0.1.0**:
Amazon Singapore search → two PDPs, plus sign-in and pagination. It did not run
these Python scripts or this exact walkthrough. See [verification and data-quality
notes](guides/verification.md) for scope, evidence limits and observed caveats.
No new live work is run by the cookbook or its tests.

Discovery at execution time is authoritative for available IDs, versions,
schemas, markets and limits; documentation isn't a maintenance bypass.

Results are snapshots, not guaranteed-current prices. Preserve the retrieval time,
source URL, Job ID, missing values and partial/failure status. Use only data you
are authorized to request and comply with applicable terms and law.

## For contributors

Keep one user problem per recipe. Include prerequisites, scope/cost implications,
commands/tool calls, polling, recovery, output interpretation and actual test
status. Add a small offline test for non-trivial code. Do not embed credentials,
real customer records, internal endpoints or fabricated output.

```sh
python3 -m unittest discover -s tests -v
```

CI runs this offline suite on Linux and Windows, Python 3.11 and 3.13. Examples
never execute live requests during tests. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) for this repository's examples and documentation. Use of the hosted
service is governed separately by the [datawebot terms](https://www.datawebot.com/terms).
