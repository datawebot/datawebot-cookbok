#!/usr/bin/env python3
"""Run one customer Job, retain its identity, and retrieve every result page. Standard library only."""
import argparse
from datetime import datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

PENDING = {"PENDING", "INITIATED"}
TERMINAL = {"COMPLETED", "PARTIAL_COMPLETE", "FAILED", "UNAVAILABLE"}


class RecipeError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a customer key to a redirect target.


def api_origin(value):
    url = urlsplit(value)
    local = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if (not url.hostname or url.username or url.password or url.path not in {"", "/"}
            or url.query or url.fragment or (url.scheme != "https" and not (local and url.scheme == "http"))):
        raise RecipeError("Use an HTTPS API origin (HTTP only on loopback), without path/query/userinfo.")
    return value.rstrip("/")


def retry_delay(value, now=None):
    if not value:
        return 0
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - (time.time() if now is None else now)
        except (ValueError, TypeError, OverflowError):
            return 0
    return max(0, seconds) if math.isfinite(seconds) else 0


def poll_delay(job, retry_after=0, now=None):
    try:
        eta = job.get("eta_delivery")
        parsed_eta = None if eta is None else datetime.fromisoformat(eta.replace("Z", "+00:00"))
        if parsed_eta is not None and parsed_eta.tzinfo is None:
            raise ValueError()
        eta_wait = 0 if parsed_eta is None else parsed_eta.timestamp() - (time.time() if now is None else now)
        guidance = job.get("poll_after_seconds", 2)
        guidance = 2 if guidance is None else float(guidance)
        if not all(math.isfinite(v) for v in [eta_wait, guidance, retry_after]) or guidance < 0:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise RecipeError("Invalid polling guidance; retain the Job ID and stop.") from None
    return max(2, eta_wait, guidance, retry_after)


def check_job(data, expected=None):
    try:
        UUID(data["job_id"])
        if data["status"] not in PENDING | TERMINAL or (expected and data["job_id"] != expected):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RecipeError("Invalid/mismatched Job response; do not submit replacement work.") from None
    return data


class API:
    def __init__(self, base, key, timeout=600):
        self.base = api_origin(base)
        if not key or re.search(r"\s", key):
            raise RecipeError("Set DATAWEBOT_API_KEY securely; never put a key in command arguments.")
        self.key = key
        self.deadline = time.monotonic() + timeout
        self.opener = build_opener(NoRedirect())

    def remaining(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise RecipeError("Waiting budget expired. Rerun with the same --state; the Job was not cancelled.")
        return left

    def pause(self, seconds):
        time.sleep(min(seconds, self.remaining()))
        self.remaining()

    def request(self, path, body=None, idempotency_key=None):
        method = "GET" if body is None else "POST"
        headers = {"Authorization": "Bearer " + self.key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        for attempt in range(3):
            request = Request(self.base + path, headers=headers, method=method,
                              data=None if body is None else json.dumps(body).encode())
            try:
                with self.opener.open(request, timeout=min(30, self.remaining())) as response:
                    raw = response.read(4 * 1024 * 1024 + 1)
                    if len(raw) > 4 * 1024 * 1024:
                        raise RecipeError("API response exceeds 4 MiB; retain Job ID and stop.")
                    data = json.loads(raw)
                    delay = retry_delay(response.headers.get("Retry-After"))
                    return data, delay
            except HTTPError as error:
                status, delay = error.code, retry_delay(error.headers.get("Retry-After"))
                error.close()
                if method == "GET" and status in {429, 502, 503, 504} and attempt < 2:
                    self.pause(max(delay, 2 ** attempt))
                    continue
                raise RecipeError(f"API HTTP {status}. Keep the state; no automatic POST retry or new Job.") from None
            except (URLError, OSError, HTTPException):
                raise RecipeError("Network/timeout error: outcome may be unknown. Rerun with the same --state, not a new one.") from None
            except (ValueError, UnicodeError):
                raise RecipeError("Invalid API JSON; retain the state and stop.") from None


def save_state(path, state, new=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise RecipeError("State must not be a symlink.")
    if new:
        with open(path, "x", encoding="utf8", opener=lambda p, flags: os.open(p, flags, 0o600)) as file:
            json.dump(state, file)
            file.write("\n")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".job-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf8") as file:
            json.dump(state, file)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def wait_job(api, response):
    job, retry_after = response
    job = check_job(job)
    identity = job["job_id"]
    while job["status"] in PENDING:
        delay = poll_delay(job, retry_after)
        print(f"{identity}: {job['status']}; next status read in {delay:.1f}s", file=sys.stderr)
        api.pause(delay)
        job, retry_after = api.request("/v1/jobs/" + identity)
        check_job(job, identity)
    return job


def retrieve_pages(api, job):
    pages, cursors, next_index = [], set(), 0
    cursor = None
    for _ in range(100):  # Bounded guard against a broken server repeating pages forever.
        query = {"page_size": 100}
        if cursor is not None:
            query["cursor"] = cursor
        page, _ = api.request("/v1/jobs/" + job["job_id"] + "/results?" + urlencode(query))
        check_job(page, job["job_id"])
        if (page["status"] != job["status"] or not isinstance(page.get("results"), list)
                or not isinstance(page.get("errors"), list) or "next_cursor" not in page):
            raise RecipeError("Invalid result page; no replacement Job was submitted.")
        for record in page["results"]:
            if (not isinstance(record, dict) or type(record.get("record_index")) is not int
                    or record["record_index"] != next_index or not isinstance(record.get("data"), dict)):
                raise RecipeError("Invalid/missing/duplicate result record; retain Job ID and stop.")
            next_index += 1
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            if "result_count" in job and (type(job["result_count"]) is not int or job["result_count"] != next_index):
                raise RecipeError("Incomplete results; retain Job ID and stop.")
            return pages
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise RecipeError("Invalid/repeated result cursor; retain Job ID and stop.")
        cursors.add(cursor)
    raise RecipeError("Too many result pages; retain Job ID and stop.")


# shortcut: one writer per checkpoint; add locking before concurrent runners share a state file.
def run(api, state_path, payload=None):
    if state_path.is_symlink():
        raise RecipeError("State must not be a symlink.")
    new_state = not state_path.exists()
    if not new_state:
        state = json.loads(state_path.read_text(encoding="utf8"))
        if (state.get("api_url") != api.base or (payload is not None and payload != state.get("request"))
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", state.get("idempotency_key", ""))):
            raise RecipeError("State belongs to a different origin/request or is invalid. Do not overwrite it.")
        payload = state["request"]
    else:
        if payload is None:
            raise RecipeError("First run requires --request request.json. Resume requires only the same --state.")
        state = {"api_url": api.base, "request": payload, "idempotency_key": str(uuid4())}
    if not isinstance(payload, dict) or not {"blueprint_id", "blueprint_version", "url", "parameters"} <= payload.keys():
        raise RecipeError("Request needs blueprint_id, blueprint_version, url and parameters. Inspect live discovery.")
    target = urlsplit(payload["url"])
    if target.scheme != "https" or not target.hostname or target.username or target.password:
        raise RecipeError("Source URL must be HTTPS without embedded credentials.")
    if "job_id" not in state:
        catalog, _ = api.request("/v1/job-blueprints")
        contract = next((b for b in catalog["blueprints"] if b["blueprint_id"] == payload["blueprint_id"]), None)
        if not contract or contract["version"] != payload["blueprint_version"] or contract.get("availability") != "ENABLED":
            raise RecipeError("Blueprint missing, version changed or in maintenance. Discover and stop; do not bypass access.")
        # Persist the exact request/key BEFORE POST, so an unknown outcome can be replayed safely.
        if new_state:
            save_state(state_path, state, new=True)
        print("Idempotency-Key: " + state["idempotency_key"], file=sys.stderr)
        response = api.request("/v1/jobs", payload, state["idempotency_key"])
        state["job_id"] = check_job(response[0])["job_id"]
        save_state(state_path, state)
    else:
        check_job({"job_id": state["job_id"], "status": "PENDING"})
        response = api.request("/v1/jobs/" + state["job_id"])
        check_job(response[0], state["job_id"])
    print("Job ID: " + state["job_id"], file=sys.stderr)
    job = wait_job(api, response)
    pages = [] if job["status"] == "UNAVAILABLE" else retrieve_pages(api, job)
    return {"job": job, "pages": pages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, help="one Job payload JSON; required only for a new state")
    parser.add_argument("--state", type=Path, required=True, help="local identity checkpoint; reuse to resume")
    parser.add_argument("--timeout", type=int, default=600, help="total wait budget, 1–3600 seconds")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be 1–3600")
    try:
        payload = json.loads(args.request.read_text(encoding="utf8")) if args.request else None
        api = API(os.environ.get("DATAWEBOT_API_URL", "https://api.datawebot.com"),
                  os.environ.get("DATAWEBOT_API_KEY"), args.timeout)
        output = run(api, args.state, payload)
        print(json.dumps(output))
        return {"COMPLETED": 0, "PARTIAL_COMPLETE": 2}.get(output["job"]["status"], 1)
    except KeyboardInterrupt:
        print("Stopped waiting, not cancelled. Resume with the same --state.", file=sys.stderr)
        return 130
    except RecipeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("Invalid local state/request/response or file operation failed. Keep state; do not submit replacement work.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
