# BrightPath AI help desk

A small help desk that answers questions about the fictional BrightPath Learn platform using only the three
documents in `docs/`. Every answer shows which document supports it, with a quote. If the documents do not
cover the question, it says so and refers the member to support instead of guessing.

Python 3.10+ and one dependency: the official Anthropic SDK. The model is Claude Haiku 5.5.

## Run it

```bash
pip install -r requirements.txt  # the Anthropic SDK (a virtual environment is recommended)
python server.py --mock          # web page at http://127.0.0.1:8000 (drop --mock once a key is set up)
python cli.py --mock "When is the group coaching session?"
python -m unittest               # unit tests (no network or key needed)
```

`python run_tests.py --mock` runs the three required cases (answered, not answered, API failure) and saves
`results/test_results.md` and `results/test_results.json`.

## Use the real model (Claude Haiku 5.5)

Settings come from environment variables or a local `.env` file (copy `.env.example` to `.env`; `.env` is
git-ignored; real environment variables win).

1. Create an API key at https://console.anthropic.com/settings/keys.
2. Set `ANTHROPIC_API_KEY=...` in `.env`. The model is `claude-haiku-5-5`; change it with `ANTHROPIC_MODEL`.
3. Run the same commands without `--mock`, and re-run `python run_tests.py` to save real-model results.

The request uses structured outputs (`output_config.format` with a JSON schema), so the API itself guarantees the
reply is valid JSON in the expected shape. The citation check below still runs on every reply.

## Mock mode

With no model available, `--mock` (or `LLM_PROVIDER=mock`) uses a keyword matcher that picks the document sentence
sharing the most words with the question. It is **not** a language model, and every mock result says so (CLI, API
JSON `"mock": true`, web page banner, saved results). If no model and no mock are configured, the app refuses with a
"no model configured" message rather than silently using the mock.

## Testing failure

- CLI: `python cli.py --simulate-failure "When is the group coaching session?"`
- Web page: tick **Simulate model failure**. API: send `{"question": "...", "simulate_failure": true}`.

This sends a real request to `http://127.0.0.1:9`, where nothing listens, so the genuine network-error code runs
(also in mock mode). The API returns HTTP 503 with `{"error": "unreachable", "message": "..."}`; the CLI prints the
message and exits with code 1.

Each failure has its own message: no model configured, unreachable, timeout, bad key (401/403), rate limit (429),
provider error (5xx), a rejected request (e.g. unknown model), a model refusal, and a reply that cannot be read.

## Hosting

The demo runs on a small Linux server as a systemd service (`deploy/brightpath-helpdesk.service`): its own
low-privilege user, a virtual environment, a `.env` file readable only by that user, and
`python server.py --host 0.0.0.0 --port 8200`. It is plain HTTP on a bare IP address, which is fine for fictional
demo data but would need HTTPS for real use.

## Design notes

- **All documents go in the prompt.** They are tiny, so there is no search index or vector database.
- **The model must reply in JSON** with `answered`, `answer` and `sources` (`doc` id plus a verbatim `quote`).
- **The code checks the citations.** A source is kept only if its doc id exists and its quote (4+ words) really
  appears in that document, ignoring case and spacing. If no source survives, the answer is replaced by a fixed
  "not available" message owned by the code, not the model.
- **The code checks the figures.** Every number, time and email address in the answer must appear in a verified
  quote. If one does not, the model's wording is replaced by the quotes themselves (`"answer_replaced": true`).
- **A second model call checks the answer.** A strict checker sees only the answer and its quotes, never the
  member's question, and says whether the quotes support every claim. If not, the quotes are shown instead. Not-found
  answers and mock answers skip it.
- **The question is treated as data.** The prompt tells the model the member's message is a question, never
  instructions, and to answer only about BrightPath.
- **The prompt carries the rules from document 3:** pricing, refunds and job placement are "not available, contact
  support", and never ask a member for a password.
- **One shared pipeline** (`helpdesk.handle_question`) serves the web API, CLI and test runner, so they behave the same.
- **Limits for a public demo:** 10 questions per visitor per minute and 300 per day in total (HTTP 429 with a clear
  message), a 10 KB request limit and a 15-second connection timeout, so a hosted copy cannot run up the API bill.
- The server binds to `127.0.0.1` by default; pass `--host 0.0.0.0` to serve it publicly. The API key is only handed to the Anthropic SDK; it is never
  printed, logged or returned.

## Files

`helpdesk.py` (core logic) · `server.py` + `static/index.html` (web) · `cli.py` · `run_tests.py` ·
`tests/test_helpdesk.py` (includes a fake Anthropic Messages API server) · `docs/` (source documents) · `results/`

## Known limits

- The code proves the quotes exist and the figures are quoted. Other made-up claims are caught by the second model
  call, which is strong evidence, not proof, and can reject a harmless paraphrase (the member then sees the quote).
- Each answered question makes two model calls, so it takes about twice as long as one.
- The mock is a crude keyword matcher: it needs two shared keywords, so short questions ("When is coaching?") may get
  "not available" in mock mode.
- No streaming. The SDK retries a failed request once (rate limit, 5xx, connection error); each attempt has a
  timeout (`LLM_TIMEOUT`, default 20 s).
- Claude is a paid API. Haiku 5.5 is its lowest-cost model, and the mock covers running with no key.
- Sending every document in every prompt only works because there are three short documents.
