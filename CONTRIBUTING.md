# Contributing

Keep examples small, task-oriented and safe for an agent to follow. No website
build, SDK abstraction or duplicate backend logic is needed here.

Each recipe states:
1. User problem and interface (API, MCP or CLI).
2. Prerequisites and explicit source-work scope.
3. Live discovery and correct current input names.
4. Polling, result pagination, idempotency and interruption recovery.
5. What the output means, including missing values/errors and timestamps.
6. Verification actually performed; synthetic fixtures must be labeled.

Run `python3 -m unittest discover -s tests -v`. Tests are offline and use
standard-library fakes/loopback HTTP only. Add regression tests when code changes.
Do not run a live example in CI. If live evidence is approved separately, record
date, bounded scope and outcome, never credentials or private customer records.

The checkpoint runner is an example, not a production SDK. One writer per state
file. State stores requests and Job IDs but no credentials. Keep it in a private
local work directory, never source control. Do not commit captured API data.
