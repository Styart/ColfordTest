# Help desk test results

- Run at: 2026-11-11T08:12:40+00:00
- Model: claude-haiku-5-5 (Anthropic API)
- Passed: 3 of 3

## 1. Supported question - PASS

- Question: When is the group coaching session?
- Simulated failure: no
- Expected: an answer with at least one document source
- HTTP status: 200
- Answered from documents: yes
- Answer: The group coaching session takes place every Tuesday at 16:00 UTC. The link appears on the Coaching page 30 minutes before the session.
- Source: Document 2 — Coaching and feedback (`02-coaching-and-feedback.md`): "A group coaching session takes place every Tuesday at 16:00 UTC."
- Source: Document 2 — Coaching and feedback (`02-coaching-and-feedback.md`): "The link appears on the Coaching page 30 minutes before the session."

## 2. Unsupported question - PASS

- Question: What is your refund policy?
- Simulated failure: no
- Expected: the fixed 'not available' message and no sources
- HTTP status: 200
- Answered from documents: no
- Answer: Sorry, that information is not available in the supplied documents. Please contact support@brightpath.example (Monday to Friday, 09:00-17:00 UTC).

## 3. API failure - PASS

- Question: When is the group coaching session?
- Simulated failure: yes
- Expected: a clear error message and a non-200 status
- HTTP status: 503
- Error: `unreachable` - The language model service at http://127.0.0.1:9 could not be reached. Check your internet connection and try again.
