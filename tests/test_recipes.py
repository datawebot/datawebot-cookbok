"""All products, Job IDs and responses here are synthetic; never contact a live service."""
import csv
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import threading
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import sys
from unittest import TestCase, main
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recipe = load("recipe", "examples/amazon-search-to-pdp/api.py")
selection = load("selection", "examples/amazon-search-to-pdp/select_asins.py")
exporter = load("exporter", "examples/results-to-csv/export.py")
ID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
REQUEST = {"blueprint_id": "amazon.search_items", "blueprint_version": "1",
           "url": "https://www.amazon.com/s?k=synthetic", "parameters": {"max_pages": 1}}
CATALOG = {"blueprints": [{"blueprint_id": "amazon.search_items", "version": "1", "availability": "ENABLED"}]}


def job(status="PENDING", identity=ID):
    return {"job_id": identity, "status": status, "eta_delivery": "2026-10-20T12:01:00Z" if status in recipe.PENDING else None,
            "poll_after_seconds": 2 if status in recipe.PENDING else None, "errors": [], "request": REQUEST.copy()}


def page(status="COMPLETED", cursor=None, index=0):
    return {**job(status), "results": [{"record_index": index, "data": {"asin": "B000000001", "title": "Synthetic fixture only",
            "url": "https://www.amazon.com/dp/B000000001"}}],
            "errors": [{"code": "fixture_failure", "message": "Synthetic error"}] if status != "COMPLETED" else [],
            "next_cursor": cursor}


class FakeAPI:
    base = "https://api.datawebot.com"

    def __init__(self, case, steps):
        self.case, self.steps, self.calls, self.waits = case, list(steps), [], []

    def request(self, path, body=None, idempotency_key=None):
        self.calls.append((path, body, idempotency_key))
        self.case.assertTrue(self.steps, "Unexpected request: " + path)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(path, body, idempotency_key) if callable(step) else (step, 0)

    def pause(self, seconds):
        self.waits.append(seconds)


class PollingTests(TestCase):
    def test_eta_guidance_and_retry_after_use_greatest(self):
        now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(recipe.poll_delay(job(), 5, now), 60)
        self.assertEqual(recipe.poll_delay(job(), 90, now), 90)
        self.assertEqual(recipe.poll_delay({**job(), "eta_delivery": None, "poll_after_seconds": 30}, 0, now), 30)
        self.assertEqual(recipe.poll_delay({**job(), "eta_delivery": None}, 0, now), 2)
        self.assertEqual(recipe.retry_delay("10", now), 10)
        self.assertEqual(recipe.retry_delay("Tue, 20 Oct 2026 12:00:20 GMT", now), 20)
        self.assertEqual(recipe.retry_delay("invalid", now), 0)
        self.assertEqual(recipe.retry_delay("nan", now), 0)

    def test_invalid_guidance_and_unknown_status_stop(self):
        for data in [{**job(), "eta_delivery": "not a date"}, {**job(), "poll_after_seconds": -1},
                     {**job(), "poll_after_seconds": "nan"}, {**job(), "eta_delivery": "2026-10-20T12:00:00"}]:
            with self.assertRaises(recipe.RecipeError):
                recipe.poll_delay(data)
        with self.assertRaises(recipe.RecipeError):
            recipe.check_job({**job(), "status": "UNKNOWN"})

    def test_wait_reads_same_identity_and_retains_terminal_failure(self):
        api = FakeAPI(self, [job("FAILED")])
        result = recipe.wait_job(api, (job(), 5))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(api.calls, [("/v1/jobs/" + ID, None, None)])
        self.assertGreaterEqual(api.waits[0], 5)
        api = FakeAPI(self, [])
        self.assertEqual(recipe.wait_job(api, (job("UNAVAILABLE"), 0))["status"], "UNAVAILABLE")
        self.assertFalse(api.waits)


class WorkflowTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "search.json"
        self.stderr = patch("sys.stderr", io.StringIO())
        self.stderr.start()
        self.addCleanup(self.stderr.stop)

    def test_search_saves_key_before_post_then_polls_and_retrieves_all_pages(self):
        def submit(path, body, key):
            saved = json.loads(self.state.read_text())
            self.assertEqual(path, "/v1/jobs")
            self.assertEqual(saved["request"], body)
            self.assertEqual(saved["idempotency_key"], key)
            self.assertNotIn("job_id", saved)
            return job(), 0
        api = FakeAPI(self, [CATALOG, submit, job("COMPLETED"), page(cursor="opaque+/=cursor"), page(index=1)])
        result = recipe.run(api, self.state, REQUEST)
        self.assertEqual(result["job"]["status"], "COMPLETED")
        self.assertEqual(len(result["pages"]), 2)
        self.assertIn("cursor=opaque%2B%2F%3Dcursor", api.calls[-1][0])
        self.assertTrue(all("page_size=100" in call[0] for call in api.calls[-2:]))
        self.assertEqual(json.loads(self.state.read_text())["job_id"], ID)
        self.assertEqual(len([call for call in api.calls if call[1] is not None]), 1)

    def test_ambiguous_post_replays_exact_saved_key_and_payload(self):
        first = FakeAPI(self, [CATALOG, recipe.RecipeError("Unknown POST outcome")])
        with self.assertRaises(recipe.RecipeError):
            recipe.run(first, self.state, REQUEST)
        saved = json.loads(self.state.read_text())
        self.assertNotIn("job_id", saved)
        second = FakeAPI(self, [CATALOG, job("COMPLETED"), page()])
        recipe.run(second, self.state)
        self.assertEqual(second.calls[1][1], first.calls[1][1])
        self.assertEqual(second.calls[1][2], saved["idempotency_key"])

    def test_resume_known_job_is_get_only_and_uses_same_id(self):
        recipe.save_state(self.state, {"api_url": FakeAPI.base, "request": REQUEST,
                          "idempotency_key": "saved-key-123", "job_id": ID}, new=True)
        api = FakeAPI(self, [job("COMPLETED"), page()])
        result = recipe.run(api, self.state)
        self.assertEqual(result["pages"][0], page())
        self.assertTrue(all(body is None for _, body, _ in api.calls))
        self.assertEqual(api.calls[0][0], "/v1/jobs/" + ID)

    def test_changed_payload_or_origin_refused_before_network(self):
        recipe.save_state(self.state, {"api_url": FakeAPI.base, "request": REQUEST,
                          "idempotency_key": "saved-key-123", "job_id": ID}, new=True)
        api = FakeAPI(self, [])
        with self.assertRaises(recipe.RecipeError):
            recipe.run(api, self.state, {**REQUEST, "url": "https://www.amazon.com/s?k=changed"})
        api.base = "https://other.example"
        with self.assertRaises(recipe.RecipeError):
            recipe.run(api, self.state)
        self.assertFalse(api.calls)

    def test_maintenance_prevents_post_and_does_not_create_checkpoint(self):
        api = FakeAPI(self, [{"blueprints": [{**CATALOG["blueprints"][0], "availability": "UNAVAILABLE"}]}])
        with self.assertRaises(recipe.RecipeError):
            recipe.run(api, self.state, REQUEST)
        self.assertFalse(self.state.exists())
        self.assertEqual(len(api.calls), 1)

    def test_unavailable_and_partial_do_not_resubmit(self):
        for status in ["UNAVAILABLE", "PARTIAL_COMPLETE", "FAILED"]:
            path = self.state.with_name(status + ".json")
            steps = [CATALOG, job(status)] + ([] if status == "UNAVAILABLE" else [page(status)])
            api = FakeAPI(self, steps)
            result = recipe.run(api, path, REQUEST)
            self.assertEqual(result["job"]["status"], status)
            self.assertEqual(len([call for call in api.calls if call[1] is not None]), 1)
            if status == "PARTIAL_COMPLETE":
                self.assertEqual(result["pages"][0]["errors"][0]["code"], "fixture_failure")

    def test_timeout_after_acceptance_retains_job_id(self):
        api = FakeAPI(self, [CATALOG, job()])
        api.pause = lambda _: (_ for _ in ()).throw(recipe.RecipeError("Waiting budget expired"))
        with self.assertRaises(recipe.RecipeError):
            recipe.run(api, self.state, REQUEST)
        self.assertEqual(json.loads(self.state.read_text())["job_id"], ID)

    def test_pagination_repeated_cursor_duplicate_index_and_mismatched_job_stop(self):
        bad_cases = [
            [page(cursor="repeat"), page(cursor="repeat", index=1)],
            [page(cursor="next"), page(index=0)],
            [{**page(), "job_id": OTHER}],
            [{**page(), "status": "FAILED"}],
            [page(index=1)],
            [page(index=True)],
        ]
        for steps in bad_cases:
            with self.assertRaises(recipe.RecipeError):
                recipe.retrieve_pages(FakeAPI(self, steps), job("COMPLETED"))

    def test_result_count_mismatch_stops_and_empty_search_is_valid(self):
        with self.assertRaises(recipe.RecipeError):
            recipe.retrieve_pages(FakeAPI(self, [page()]), {**job("COMPLETED"), "result_count": 2})
        empty = {**page(), "results": []}
        self.assertEqual(recipe.retrieve_pages(FakeAPI(self, [empty]), {**job("COMPLETED"), "result_count": 0}), [empty])

    def test_job_identity_is_saved_before_first_wait(self):
        api = FakeAPI(self, [CATALOG, job(), job("COMPLETED"), page()])
        def pause(_):
            self.assertEqual(json.loads(self.state.read_text())["job_id"], ID)
        api.pause = pause
        recipe.run(api, self.state, REQUEST)

    def test_existing_checkpoint_cannot_be_accidentally_created_again(self):
        recipe.save_state(self.state, {"original": True}, new=True)
        with self.assertRaises(FileExistsError):
            recipe.save_state(self.state, {"overwrite": True}, new=True)
        self.assertEqual(json.loads(self.state.read_text()), {"original": True})


class TransportTests(TestCase):
    def test_unsafe_origins_and_missing_keys_fail_before_requests(self):
        for origin in ["http://remote.example", "https://user:pass@example.com", "https://example.com/v1", "https://example.com/?x=y"]:
            with self.assertRaises(recipe.RecipeError):
                recipe.API(origin, "synthetic-key")
        self.assertEqual(recipe.api_origin("http://127.0.0.1:8792"), "http://127.0.0.1:8792")
        with self.assertRaises(recipe.RecipeError):
            recipe.API(FakeAPI.base, None)

    def test_get_retry_honors_retry_after_but_post_never_retries(self):
        api = recipe.API(FakeAPI.base, "synthetic-key")
        delays = []
        api.pause = delays.append
        error = lambda: HTTPError(FakeAPI.base, 429, "busy", {"Retry-After": "7"}, io.BytesIO(b"{}"))
        response = io.BytesIO(b'{"ok":true}')
        response.headers = {}
        with patch.object(api.opener, "open", side_effect=[error(), response]) as opener:
            self.assertEqual(api.request("/v1/account")[0], {"ok": True})
            self.assertEqual(opener.call_count, 2)
        self.assertEqual(delays, [7])
        with patch.object(api.opener, "open", side_effect=error()) as opener:
            with self.assertRaises(recipe.RecipeError):
                api.request("/v1/jobs", REQUEST, "saved-key-123")
            self.assertEqual(opener.call_count, 1)

    def test_network_errors_do_not_echo_key_and_do_not_retry_post(self):
        api = recipe.API(FakeAPI.base, "synthetic-secret-key")
        with patch.object(api.opener, "open", side_effect=URLError("synthetic-secret-key")) as opener:
            with self.assertRaises(recipe.RecipeError) as caught:
                api.request("/v1/jobs", REQUEST, "saved-key-123")
            self.assertNotIn("synthetic-secret-key", str(caught.exception))
            self.assertEqual(opener.call_count, 1)

    def test_incomplete_http_response_does_not_leak_body_or_retry_post(self):
        api = recipe.API(FakeAPI.base, "synthetic-secret-key")
        with patch.object(api.opener, "open", side_effect=IncompleteRead(b"synthetic-secret-key")) as opener:
            with self.assertRaises(recipe.RecipeError) as caught:
                api.request("/v1/jobs", REQUEST, "saved-key-123")
            self.assertNotIn("synthetic-secret-key", str(caught.exception))
            self.assertEqual(opener.call_count, 1)

    def test_loopback_http_runs_one_job_and_resumes_without_post(self):
        calls = []
        case = self

        class Handler(BaseHTTPRequestHandler):
            def send_json(self, data):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def do_POST(self):
                calls.append(("POST", self.path))
                case.assertEqual(self.path, "/v1/jobs")
                case.assertEqual(json.loads(self.rfile.read(int(self.headers["Content-Length"]))), REQUEST)
                case.assertEqual(self.headers["Authorization"], "Bearer synthetic-key")
                case.assertTrue(self.headers["Idempotency-Key"])
                self.send_json(job())

            def do_GET(self):
                calls.append(("GET", self.path))
                case.assertEqual(self.headers["Authorization"], "Bearer synthetic-key")
                if self.path == "/v1/job-blueprints":
                    self.send_json(CATALOG)
                elif self.path == "/v1/jobs/" + ID:
                    self.send_json({**job("COMPLETED"), "result_count": 2})
                elif self.path == "/v1/jobs/" + ID + "/results?page_size=100":
                    self.send_json(page(cursor="opaque+/=cursor"))
                elif self.path == "/v1/jobs/" + ID + "/results?page_size=100&cursor=opaque%2B%2F%3Dcursor":
                    self.send_json(page(index=1))
                else:
                    self.send_error(404)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory, patch("sys.stderr", io.StringIO()):
                api = recipe.API("http://127.0.0.1:" + str(server.server_port), "synthetic-key")
                waits = []
                api.pause = waits.append
                state = Path(directory) / "state.json"
                output = recipe.run(api, state, REQUEST)
                self.assertEqual(len(output["pages"]), 2)
                self.assertEqual(len(waits), 1)
                before_resume = len(calls)
                resumed = recipe.run(api, state)
                self.assertEqual(resumed, output)
                self.assertTrue(all(method == "GET" for method, _ in calls[before_resume:]))
                self.assertEqual(sum(method == "POST" for method, _ in calls), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_redirect_is_not_followed_to_second_endpoint(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/must-not-follow")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = recipe.API("http://127.0.0.1:" + str(server.server_port), "synthetic-key")
            with self.assertRaises(recipe.RecipeError):
                api.request("/original")
            self.assertEqual(calls, ["/original"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class LocalDataTests(TestCase):
    def test_asins_are_deduplicated_in_observed_order_and_marketplace_preserved(self):
        first = page()
        first["request"]["url"] = "https://www.amazon.sg/s?k=synthetic"
        first["results"][0]["data"]["url"] = "https://www.amazon.sg/dp/B000000001"
        first["results"].append({"record_index": 1, "data": first["results"][0]["data"].copy()})
        first["results"].append({"record_index": 2, "data": {"asin": "B000000002", "url": "https://www.amazon.sg/dp/B000000002"}})
        result = selection.select({"job": first, "pages": [first]})
        self.assertEqual([item["asin"] for item in result], ["B000000001", "B000000002"])
        self.assertEqual(result[1]["url"], "https://www.amazon.sg/dp/B000000002")

    def test_partial_selection_and_invalid_asin_url_are_refused(self):
        with self.assertRaises(ValueError):
            selection.select({"job": job("PARTIAL_COMPLETE"), "pages": [page("PARTIAL_COMPLETE")]})
        bad = page()
        bad["results"][0]["data"]["asin"] = "B000000999"
        with self.assertRaises(ValueError):
            selection.select({"job": job("COMPLETED"), "pages": [bad]})

    def test_cli_pages_deduplicate_without_sorting_candidates(self):
        first = page(cursor="next")
        first["results"][0]["data"] = {"asin": "B000000002", "url": "https://www.amazon.com/dp/B000000002"}
        second = page(index=1)
        self.assertEqual([item["asin"] for item in selection.select([first, second])], ["B000000002", "B000000001"])
        self.assertEqual(selection.select({"job": first, "pages": [first, second]}), selection.select([first, second]))

    def test_selection_rejects_incomplete_mixed_and_out_of_order_pages(self):
        bad_cases = [
            [page(cursor="unread")],
            [page(), page(index=1)],
            [page(cursor="next"), page(index=0)],
            [page(index=1)],
            [page(index=True)],
            [page(cursor="next"), {**page(index=1), "job_id": OTHER}],
            [{**page(), "errors": [{"code": "unexpected"}]}],
            [{**page(), "result_count": 2}],
            [{**page(), "request": {**REQUEST, "blueprint_id": "amazon.product_details"}}],
        ]
        for pages in bad_cases:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                selection.select(pages)
        wrong_market = page()
        wrong_market["results"][0]["data"]["url"] = "https://www.amazon.sg/dp/B000000001"
        with self.assertRaises(ValueError):
            selection.select([wrong_market])

    def test_empty_search_has_no_candidates(self):
        empty = {**page(), "results": [], "result_count": 0}
        self.assertEqual(selection.select([empty]), [])
        with self.assertRaises(ValueError):
            selection.select([])

    def test_selection_script_accepts_api_envelope_and_ordered_cli_files(self):
        with tempfile.TemporaryDirectory() as directory:
            files = [Path(directory) / name for name in ["page1.json", "page2.json", "envelope.json"]]
            first, second = page(cursor="next"), page(index=1)
            for file, data in zip(files, [first, second, {"job": job("COMPLETED"), "pages": [first, second]}]):
                file.write_text(json.dumps(data), encoding="utf8")
            command = [sys.executable, str(ROOT / "examples/amazon-search-to-pdp/select_asins.py")]
            cli = json.loads(subprocess.check_output(command + [str(file) for file in files[:2]], text=True))
            api = json.loads(subprocess.check_output(command + [str(files[2])], text=True))
            self.assertEqual(cli, api)
            self.assertEqual(len(cli), 1)
            incomplete = subprocess.run(command + [str(files[0])], capture_output=True, text=True)
            self.assertNotEqual(incomplete.returncode, 0)
            self.assertEqual(incomplete.stdout, "")

    def test_csv_preserves_nested_data_null_and_partial_status(self):
        data = {"title": '=HYPERLINK("bad")', "price": None, "variants": [{"size": "M"}]}
        partial = page("PARTIAL_COMPLETE")
        partial["results"][0]["data"] = data
        out = io.StringIO()
        exporter.export({"job": job("PARTIAL_COMPLETE"), "pages": [partial]}, out)
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(rows[0]["job_status"], "PARTIAL_COMPLETE")
        self.assertEqual(json.loads(rows[0]["data_json"]), data)
        for text in ["=1+1", "+formula", "-1", "@SUM(1)", " \t=1", "\ntext"]:
            self.assertTrue(exporter.safe_cell(text).startswith("'"))
        self.assertEqual(exporter.safe_cell(None), "")

    def test_public_docs_link_only_to_public_github_organization(self):
        for path in ROOT.rglob("*.md"):
            if ".git" not in path.parts:
                for owner in re.findall(r"https://github.com/([^/\s)]+)", path.read_text(encoding="utf8")):
                    self.assertEqual(owner, "datawebot", str(path.relative_to(ROOT)))

    def test_markdown_relative_links_resolve(self):
        for path in ROOT.rglob("*.md"):
            if ".git" in path.parts:
                continue
            for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf8")):
                if "://" not in link and not link.startswith("#"):
                    target = path.parent / link.split("#")[0]
                    self.assertTrue(target.exists(), f"Broken link in {path.relative_to(ROOT)}: {link}")


if __name__ == "__main__":
    main()
