"""Unit tests. Run with: python -m unittest"""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import helpdesk
import server

DOCS = helpdesk.load_docs()
COACHING = "A group coaching session takes place every Tuesday at 16:00 UTC."


def settings_for(base_url, timeout=5):
    return {"provider": "claude", "base_url": base_url, "api_key": "test-key", "model": "fake-model",
            "timeout": timeout, "max_retries": 0, "configured": True}


def good_reply(doc="doc2", quote=COACHING):
    return json.dumps({"answered": True, "answer": "Tuesdays at 16:00 UTC.", "sources": [{"doc": doc, "quote": quote}]})


class FakeClaude(BaseHTTPRequestHandler):
    """A tiny stand-in for the Anthropic Messages API. The first path segment picks the behaviour,
    e.g. /401/v1/messages. It records every request so a test can check what the SDK sent."""
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeClaude.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        mode = self.path.split("/")[1]
        if mode == "slow":
            time.sleep(2)
        if mode in ("401", "429", "500"):
            reply, status = {"type": "error", "error": {"type": "api_error", "message": "nope"}}, int(mode)
        else:
            if body["system"] == helpdesk.CHECK_PROMPT:  # the second request: the answer checker
                text = json.dumps({"supported": mode != "unsupported"})
            else:
                text = good_reply() if mode in ("ok", "unsupported") else "I think it is Tuesday."
            reply, status = {"id": "msg_test", "type": "message", "role": "assistant", "model": "fake-model",
                             # a real reply can start with a thinking block, so the fake one does too
                             "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                                         {"type": "text", "text": text}],
                             "stop_reason": "refusal" if mode == "refusal" else "end_turn", "stop_sequence": None,
                             "usage": {"input_tokens": 1, "output_tokens": 1}}, 200
        body = b"<html>not json</html>" if mode == "garbage" else json.dumps(reply).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html" if mode == "garbage" else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output quiet
        pass


class ValidationTests(unittest.TestCase):
    def validate(self, raw):
        return helpdesk.validate_answer(helpdesk.parse_model_json(raw), DOCS)

    def test_valid_source_is_kept(self):
        result = self.validate(good_reply())
        self.assertTrue(result["answered"])
        self.assertEqual(result["sources"][0]["file"], "02-coaching-and-feedback.md")

    def test_quote_matching_ignores_case_and_whitespace(self):
        self.assertTrue(self.validate(good_reply(quote="  a GROUP coaching\n session takes place  "))["answered"])

    def test_unknown_doc_id_downgrades_to_not_found(self):
        result = self.validate(good_reply(doc="doc9"))
        self.assertFalse(result["answered"])
        self.assertEqual(result["answer"], helpdesk.NOT_FOUND_ANSWER)
        self.assertEqual(result["rejected_sources"], 1)

    def test_quote_not_in_cited_doc_downgrades(self):
        self.assertFalse(self.validate(good_reply(doc="doc1"))["answered"])  # real quote, wrong document
        self.assertFalse(self.validate(good_reply(quote="Refunds are given within 30 days."))["answered"])

    def test_too_short_quote_is_rejected(self):
        self.assertFalse(self.validate(good_reply(quote="UTC"))["answered"])

    def test_answered_without_sources_downgrades(self):
        raw = json.dumps({"answered": True, "answer": "Refunds take 30 days.", "sources": []})
        self.assertEqual(self.validate(raw)["answer"], helpdesk.NOT_FOUND_ANSWER)

    def test_one_bad_source_is_dropped_good_one_kept(self):
        data = json.loads(good_reply())
        data["sources"].append({"doc": "doc3", "quote": "Made up sentence that is not there."})
        result = helpdesk.validate_answer(data, DOCS)
        self.assertEqual((len(result["sources"]), result["rejected_sources"]), (1, 1))

    def test_sources_that_are_not_a_list_mean_not_found(self):
        for sources in (5, True, "doc2", {"doc": "doc2", "quote": COACHING}):
            data = {"answered": True, "answer": "Tuesdays.", "sources": sources}
            self.assertEqual(helpdesk.validate_answer(data, DOCS)["answer"], helpdesk.NOT_FOUND_ANSWER, sources)

    def answer_with(self, answer, quote=COACHING, doc="doc2"):
        data = {"answered": True, "answer": answer, "sources": [{"doc": doc, "quote": quote}]}
        return helpdesk.validate_answer(data, DOCS)

    def test_answer_with_quoted_figures_is_kept(self):
        result = self.answer_with("Coaching is on Tuesdays at 16:00 UTC.")
        self.assertEqual((result["answer"], result["answer_replaced"]), ("Coaching is on Tuesdays at 16:00 UTC.", False))

    def test_answer_with_unquoted_figures_is_replaced_by_the_quotes(self):
        for answer in ("Coaching is on Tuesdays at 17:00 UTC.",                  # wrong time next to a real quote
                       "Tuesdays at 16:00 UTC. The course costs $5 a month.",    # invented price
                       "Tuesdays at 16:00 UTC. Email help@evil.example."):       # invented contact address
            result = self.answer_with(answer)
            self.assertTrue(result["answered"], answer)
            self.assertEqual((result["answer"], result["answer_replaced"]), (COACHING, True), answer)

    def test_support_address_is_always_allowed_but_its_hours_are_not(self):
        # The address comes from the app's own "not available" message, so the model may repeat it without a quote.
        answer = "Tuesdays at 16:00 UTC. For anything else contact support@brightpath.example."
        self.assertFalse(self.answer_with(answer)["answer_replaced"])
        self.assertTrue(self.answer_with(answer + " They are open 09:00-17:00 UTC.")["answer_replaced"])

    def test_code_fenced_json_is_parsed(self):
        self.assertTrue(self.validate("```json\n" + good_reply() + "\n```")["answered"])

    def test_malformed_json_raises_bad_response(self):
        for raw in ("not json at all", "{broken", None, "[1, 2]"):
            with self.assertRaises(helpdesk.HelpDeskError) as ctx:
                self.validate(raw)
            self.assertEqual(ctx.exception.kind, "bad_response")


class ErrorMappingTests(unittest.TestCase):
    def test_http_status_mapping(self):
        expected = {401: ("auth", 502), 403: ("auth", 502), 429: ("rate_limited", 429),
                    500: ("upstream_error", 502), 503: ("upstream_error", 502), 404: ("bad_request", 502)}
        for status, (kind, api_status) in expected.items():
            err = helpdesk.http_error(status)
            self.assertEqual((err.kind, err.status), (kind, api_status), status)

    def test_no_model_configured(self):
        settings = dict(settings_for(None), api_key="", configured=False)
        status, payload = helpdesk.handle_question("When is coaching?", settings)
        self.assertEqual((status, payload["error"]), (503, "no_model_configured"))

    def test_empty_question(self):
        status, payload = helpdesk.handle_question("   ", settings_for("http://unused"))
        self.assertEqual((status, payload["error"]), (400, "empty_question"))


class HttpClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeClaude)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def ask(self, mode, timeout=5):
        return helpdesk.handle_question("When is the group coaching session?", settings_for(f"{self.url}/{mode}", timeout))

    def test_success_through_real_http_path(self):
        FakeClaude.requests.clear()
        status, payload = self.ask("ok")
        self.assertEqual(status, 200)
        self.assertTrue(payload["answered"])
        self.assertFalse(payload["mock"] or payload["answer_replaced"])
        sent, check = FakeClaude.requests  # what the Anthropic SDK actually sent: the question, then the check
        self.assertEqual((sent["path"], sent["auth"]), ("/ok/v1/messages", "Bearer test-key"))
        self.assertEqual(sent["body"]["model"], "fake-model")
        self.assertEqual(sent["body"]["output_config"]["format"]["type"], "json_schema")
        self.assertIn("Document 2", sent["body"]["system"])
        self.assertNotIn("temperature", sent["body"])  # Haiku 5.5 rejects sampling parameters
        check_message = check["body"]["messages"][0]["content"]
        self.assertIn(COACHING, check_message)             # the checker gets the quote and the answer...
        self.assertIn("Tuesdays at 16:00 UTC.", check_message)
        self.assertNotIn("When is the group", check_message)  # ...but never the member's question

    def test_answer_the_checker_rejects_is_replaced_by_the_quotes(self):
        status, payload = self.ask("unsupported")
        self.assertEqual((status, payload["answered"]), (200, True))
        self.assertEqual((payload["answer"], payload["answer_replaced"]), (COACHING, True))

    def test_not_found_answers_skip_the_checker(self):
        FakeClaude.requests.clear()
        with unittest.mock.patch.object(helpdesk, "validate_answer", return_value=helpdesk.not_found()):
            self.ask("ok")
        self.assertEqual(len(FakeClaude.requests), 1)

    def test_error_statuses(self):
        for mode, kind in (("401", "auth"), ("429", "rate_limited"), ("500", "upstream_error"),
                           ("garbage", "bad_response"), ("prose", "bad_response"), ("refusal", "refused")):
            status, payload = self.ask(mode)
            self.assertNotEqual(status, 200, mode)
            self.assertEqual(payload["error"], kind, mode)
            self.assertNotIn("test-key", json.dumps(payload))  # the key never leaks into a response

    def test_timeout(self):
        status, payload = self.ask("slow", timeout=0.5)
        self.assertEqual((status, payload["error"]), (504, "timeout"))

    def test_simulated_failure_uses_real_client_even_in_mock_mode(self):
        status, payload = helpdesk.handle_question("When is the group coaching session?",
                                                   dict(settings_for(""), provider="mock"), simulate_failure=True)
        self.assertIn(payload["error"], ("unreachable", "timeout"))
        self.assertTrue(payload["mock"] and payload["simulated_failure"])
        self.assertIn(status, (503, 504))


class EnvFileTests(unittest.TestCase):
    def test_bom_and_utf16_files_from_windows_powershell(self):
        for encoding in ("utf-8-sig", "utf-16"):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / ".env"
                path.write_text("ANTHROPIC_MODEL=from-file\n", encoding=encoding)
                with unittest.mock.patch.dict(os.environ, clear=True):
                    helpdesk.load_env_file(path)
                    self.assertEqual(os.environ.get("ANTHROPIC_MODEL"), "from-file", encoding)


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        server.recent.clear()
        server.today.update(date="", count=0)

    tearDown = setUp  # leave the counters clean for the other tests

    def test_per_visitor_limit_resets_after_a_minute(self):
        for _ in range(server.PER_MINUTE_LIMIT):
            self.assertIsNone(server.over_limit("1.2.3.4", now=1000))
        self.assertIn("wait a minute", server.over_limit("1.2.3.4", now=1001))
        self.assertIsNone(server.over_limit("5.6.7.8", now=1001))  # another visitor is not affected
        self.assertIsNone(server.over_limit("1.2.3.4", now=1061))  # a minute later it works again

    def test_daily_limit_covers_all_visitors(self):
        for number in range(server.DAILY_LIMIT):
            self.assertIsNone(server.over_limit(f"visitor-{number}", now=1000))
        self.assertIn("daily", server.over_limit("someone-new", now=1000))
        self.assertIsNone(server.over_limit("someone-new", now=1000 + 86400))  # the next day


class ServerTests(unittest.TestCase):
    def test_invalid_content_length_gets_a_clear_400(self):
        class QuietHandler(server.Handler):
            def log_message(self, *args):
                pass

        web = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        web.settings = dict(settings_for(""), provider="mock")
        threading.Thread(target=web.serve_forever, daemon=True).start()
        try:
            for value in ("abc", "-1"):  # -1 used to make the server read past the size limit
                conn = http.client.HTTPConnection("127.0.0.1", web.server_address[1], timeout=5)
                conn.putrequest("POST", "/api/ask")
                conn.putheader("Content-Length", value)
                conn.endheaders()
                response = conn.getresponse()
                self.assertEqual((response.status, json.load(response)["error"]), (400, "bad_length"), value)
                conn.close()
        finally:
            web.shutdown()
            web.server_close()


class MockModelTests(unittest.TestCase):
    mock = dict(settings_for(""), provider="mock")

    def test_supported_question(self):
        status, payload = helpdesk.handle_question("When is the group coaching session?", self.mock)
        self.assertEqual(payload["sources"][0]["quote"], COACHING)
        self.assertTrue(payload["mock"])

    def test_restricted_topic_is_not_answered(self):
        status, payload = helpdesk.handle_question("What is your refund policy?", self.mock)
        self.assertEqual(payload["answer"], helpdesk.NOT_FOUND_ANSWER)


if __name__ == "__main__":
    unittest.main()
