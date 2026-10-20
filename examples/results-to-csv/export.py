#!/usr/bin/env python3
"""Export saved API recipe pages to CSV locally; no datawebot calls."""
import argparse
import csv
import json
from pathlib import Path
import sys


def safe_cell(value):
    if value is None:
        return ""
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    # Source text is untrusted: prevent spreadsheet formula execution, including leading whitespace.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


def export(document, output):
    job = document["job"]
    if job["status"] not in {"COMPLETED", "PARTIAL_COMPLETE"}:
        raise ValueError("Only completed/partial result pages can be exported.")
    rows = []
    for page in document["pages"]:
        if page["job_id"] != job["job_id"] or page["status"] != job["status"]:
            raise ValueError("Mismatched page.")
        for record in page["results"]:
            rows.append({"job_id": job["job_id"], "job_status": job["status"],
                         "record_index": record["record_index"], "data_json": json.dumps(record["data"], ensure_ascii=False)})
    writer = csv.DictWriter(output, fieldnames=["job_id", "job_status", "record_index", "data_json"], lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: safe_cell(value) for key, value in row.items()} for row in rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="saved output JSON from api.py")
    args = parser.parse_args()
    try:
        export(json.loads(args.input.read_text(encoding="utf8")), sys.stdout)
    except (OSError, ValueError, KeyError, TypeError):
        sys.exit("Invalid input. Supply saved api.py output with completed/partial pages.")
