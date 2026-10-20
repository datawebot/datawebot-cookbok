#!/usr/bin/env python3
"""Deduplicate ASINs from saved API/CLI search pages in observed order; no network calls."""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


def select(document):
    # Accept the API runner's envelope or an ordered list of unchanged CLI pages.
    pages = document["pages"] if isinstance(document, dict) else document
    if not isinstance(pages, list) or not pages:
        raise ValueError("Supply every search result page in order.")
    job = document["job"] if isinstance(document, dict) else pages[0]
    if job["status"] != "COMPLETED":
        raise ValueError("Review partial/failed results before selecting products; no automatic PDP fan-out.")
    request = job["request"]
    source = urlsplit(request["url"])
    market = source.hostname
    if (request["blueprint_id"] != "amazon.search_items" or source.scheme != "https"
            or not market or source.username or source.password):
        raise ValueError("Supply search results with their original request metadata.")
    seen, selected, cursors = set(), [], set()
    expected_index = 0
    for number, page in enumerate(pages):
        if page["job_id"] != job["job_id"] or page["status"] != "COMPLETED" or page.get("errors") != []:
            raise ValueError("Mismatched or erroneous result page.")
        cursor = page["next_cursor"]
        if number == len(pages) - 1:
            if cursor is not None:
                raise ValueError("Retrieve all remaining result pages before selecting products.")
        elif not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise ValueError("Invalid result page sequence.")
        cursors.add(cursor)
        for record in page["results"]:
            index = record["record_index"]
            if type(index) is not int or index != expected_index:
                raise ValueError("Missing, repeated or out-of-order result record.")
            expected_index += 1
            data = record["data"]
            asin, url = data["asin"], data["url"]
            target = urlsplit(url)
            match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)", target.path)
            if (not re.fullmatch(r"[A-Z0-9]{10}", asin) or target.scheme != "https"
                    or target.username or target.password or not target.hostname or not match or match[1] != asin
                    or target.hostname.removeprefix("www.") != market.removeprefix("www.")):
                raise ValueError("Invalid ASIN/product URL or changed marketplace; inspect records instead of guessing.")
            if asin not in seen:
                seen.add(asin)
                selected.append({"asin": asin, "url": url})
    if "result_count" in job and (type(job["result_count"]) is not int or job["result_count"] != expected_index):
        raise ValueError("Result count mismatch; retain all pages before selecting products.")
    return selected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="+", help="api.py envelope OR CLI result pages in page order")
    args = parser.parse_args()
    try:
        documents = [json.loads(path.read_text(encoding="utf8")) for path in args.input]
        document = documents[0] if len(documents) == 1 and "pages" in documents[0] else documents
        print(json.dumps(select(document)))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        sys.exit("Invalid, incomplete or non-completed input. Review records before submitting PDP Jobs.")
