# Provenance Guard

A Flask backend for text attribution, cautious transparency labels, creator appeals, and persistent structured audit events. It is an educational prototype: writing style cannot establish authorship.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock.txt
cp .env.example .env
python app.py
```

Default mode runs offline and requires no account. SQLite creates `provenance.sqlite3` on first startup. The server binds to `127.0.0.1:5000`; debug mode is disabled. `requirements.txt` describes acceptable dependency ranges; `requirements.lock.txt` records the versions actually tested.

Optional semantic signal: set `DETECTION_MODE=groq`, `GROQ_API_KEY`, and `GROQ_MODEL` in `.env` to a model enabled in your account that supports JSON output. This uses the Groq REST API through Python's standard library rather than requiring its SDK. Text is sent to that provider in this mode. Missing configuration, invalid output, or network failures force an uncertain result. Live Groq calls have **not** been verified; automated tests exercise failure handling. Offline mode remains fully functional.

## Architecture overview

The API validates JSON and applies submission limits before sending text to two independent measurement functions. A discourse score and a structural stylometry score feed weighted scoring and uncertainty rules; the exact label and full signal output are saved with the content in a SQLite transaction. The response supplies a UUID for subsequent retrieval and appeals. An appeal checks the supplied creator ID, changes the content to `under_review`, and appends a new audit event while preserving the original decision. See [planning.md](planning.md) for the diagram and the specification written before implementation.

| Endpoint | Contract |
| --- | --- |
| `POST /submit` | `text`, `creator_id`; returns ID, attribution, confidence, AI index, exact label, signals, timestamp, status |
| `POST /appeal` | `content_id`, `creator_id`, `creator_reasoning`; returns current record with `under_review` status |
| `GET /content/<id>` | Current stored decision and appeal state; 404 if missing |
| `GET /log` | Most recent 100 structured audit events, newest first |
| `GET /health` | JSON health response |

Text must be nonempty and at most 20,000 characters; creator IDs at most 100 characters; appeal reasoning at most 4,000 characters. Malformed fields return 400, oversized HTTP bodies 413, mismatched appeal creators 403, absent content 404, duplicate appeals 409, and rate limits 429.

```bash
curl -s http://127.0.0.1:5000/submit \
  -H 'Content-Type: application/json' \
  -d '{"text":"I wrote this little draft while waiting for the train.","creator_id":"writer-1"}'

# Replace CONTENT_ID with the ID returned above.
curl -s http://127.0.0.1:5000/appeal \
  -H 'Content-Type: application/json' \
  -d '{"content_id":"CONTENT_ID","creator_id":"writer-1","creator_reasoning":"I wrote this myself and can provide drafts."}'

curl -s http://127.0.0.1:5000/log
```

## Detection signals and their limits

**Lexical discourse:** measures stock transitions/generic assertions (such as “it is important to note”) and conversational cues (such as “ok so”). Start at 0.5, add 0.12 per matched stock phrase, subtract 0.10 per conversational cue, and clamp to [0.05, 0.95]. These choices provide an inspectable discourse signal without API dependencies. They are hand-designed hypotheses, not validated linguistic evidence. Academic human prose can trigger stock phrases; AI can imitate casual language. Optional Groq replaces this function with a semantic assessment between 0 and 1; it is not counted as a third signal.

**Stylometry:** measures sentence length coefficient of variation (CV), type-token ratio (TTR), and distinct punctuation types. Score = `0.65*(1-min(CV,1)) + 0.25*(1-TTR) + 0.10*(1-min(punctuation_types/5,1))`. Uniform sentence structure and repeated vocabulary increase the index. These are structural properties distinct from discourse phrases, although neither signal is statistically independent of writing style. Poetry, dialogue, punctuation conventions, and text length can distort these metrics.

## Confidence scoring and validation

`ai_score = 0.65*discourse + 0.35*stylometry`. At least 0.80 means `likely_ai`; at most 0.30 means `likely_human`; everything between is `uncertain`. The higher AI threshold reflects the greater harm of accusing a human creator incorrectly. Fewer than 35 words, disagreement greater than 0.50, or provider failure force uncertainty and constrain the index to [0.31, 0.79].

`confidence = max(ai_score, 1-ai_score)` expresses heuristic strength toward either end of the index. It is **not** the probability that the selected label is correct, especially for uncertain decisions; clients should display the plain-language label rather than a probability percentage. The API explicitly returns `confidence_kind=heuristic_strength_not_probability`. An AI index of 0.51 yields uncertainty, while 0.95 can yield likely AI when both signals support it and sufficient text is present.

Actual offline endpoint results are in [evidence/examples.json](evidence/examples.json), including full input texts and per-signal measurements:

| Example | AI index | Confidence strength | Attribution |
| --- | ---: | ---: | --- |
| Deliberately uniform synthetic paragraph, beginning “Furthermore, stakeholders in modern society…” | 0.913396 | 0.913396 | likely_ai |
| Course AI-style paragraph, beginning “Artificial intelligence represents…” | 0.789886 | 0.789886 | uncertain |
| Casual ramen account, beginning “ok so i finally tried…” | 0.153090 | 0.846910 | likely_human |
| Formal monetary-policy paragraph | 0.534512 | 0.534512 | uncertain |
| Edited AI-style remote-work paragraph | 0.423560 | 0.576440 | uncertain |

The synthetic paragraph confirms the high-confidence category is reachable; the formal passage is a lower-confidence example. All four supplied examples were checked, with a fifth to demonstrate all labels. The supplied AI-style passage remains uncertain because it falls below the conservative threshold; the threshold was not lowered just to make that example pass. These style fixtures demonstrate score variation and rule behavior, **not empirical detection accuracy or calibration**. The course examples have no independently verified authorship. Deployment would require consented, held-out human and AI corpora, false-positive analysis across genres and writer populations, and calibration measurements.

## Exact transparency labels

| Attribution | Verbatim label |
| --- | --- |
| High-confidence AI | "Likely AI-generated. Multiple writing signals support this assessment, but it is not proof of authorship. The creator can appeal." |
| High-confidence human | "Likely human-written. Writing signals support human authorship, but this does not verify who wrote it." |
| Uncertain | "Authorship uncertain. The available writing signals are inconclusive; no reliable human or AI attribution can be made." |

## Appeals

Creators submit reasoning against a content ID with their matching creator ID. The transaction retains the original attribution, scores, and label, changes status to `under_review`, and appends an appeal event with `appeal_reasoning`, a new event timestamp, and the original timestamp. Reviewers can inspect `/log` alongside `/content/<id>`. A second appeal returns 409 and cannot overwrite the original reasoning. Unknown content and creator mismatch fail without modifying storage. Automated reassessment and reviewer resolution are outside this project's required scope.

Creator ID matching is a demonstration ownership check, not authentication: an attacker who knows an ID could impersonate its creator. No actual verified-human credential is claimed.

## Rate limiting

The committed `/submit` decorator specifies **10 requests per minute and 100 per day per remote IP**, with explicit `storage_uri="memory://"`. Ten per minute permits draft revisions and interactive testing; 100 per day permits substantial writing activity while bounding accidental loops and single-client flooding. Rejected requests also consume limit capacity. Appeals additionally permit 10 per minute.

[evidence/rate-limit.txt](evidence/rate-limit.txt) records actual endpoint status codes from a fresh Flask test client sending 12 requests:

```text
200
200
200
200
200
200
200
200
200
200
429
429
```

The test client exercises Flask-Limiter middleware directly; this is not a fabricated curl transcript. The minute limit was tested; the daily limit is configured but was not time-travel tested. Memory counters reset on process restart and are not shared across workers. Shared-IP creators also share quotas. Production needs shared storage, authenticated user limits, and carefully configured proxy handling. The application does not trust spoofable forwarded-IP headers by default.

## Structured audit log

[evidence/audit-sample.json](evidence/audit-sample.json) contains six real events: five classifications and one appeal. Every event includes UTC timestamp, content ID, creator ID, attribution, confidence, AI index, full signal scores/metrics, exact label, status, and appeal flag. The appeal event includes reasoning and the original decision details. Content changes and audit inserts are atomic SQLite transactions; the original classification event remains unchanged. `/log` returns newest events first, capped at 100. SQLite retains earlier entries.

## Tests

```bash
source .venv/bin/activate
python -m unittest -v
python test_app.py --evidence
```

Seven tests pass. They cover the five writing fixtures and exact label mapping; invalid submissions and short-text abstention; appeal ownership, missing IDs, duplicate appeals, original-event preservation, and persistence across app instances; 12-request rate-limit enforcement; threshold boundaries and disagreement; provider failure, malformed boolean scores, and missing or malformed provider explanations. Evidence generation uses temporary databases and does not change your application database. Timestamps and UUIDs change on regeneration.

## Known limitations

Formal human essays can match stock phrases and uniform structure, causing false positives. Repetitive poetry can look generated because repeated words lower TTR; expressive AI writing can evade both signals. English phrase matching is poorly suited to other languages. Naive sentence splitting mishandles abbreviations, and TTR is length-dependent. Provider prompts can be manipulated despite treating content as untrusted input. An LLM's self-reported score is also not calibrated.

This local prototype has public log/content endpoints, stores raw text and appeal reasoning, and lacks real authentication, retention rules, reviewer authorization, and a resolution endpoint. Use only demonstration data. Production would require those controls, shared rate-limit storage, robust multilingual evaluation, and database operational safeguards. No stretch features are claimed.

## Spec reflection

Writing thresholds, verbatim labels, and duplicate-appeal behavior before implementation made it possible to assert endpoint behavior directly and keep original decisions intact. The first scoring test assumed the course AI-style example would receive `likely_ai`; implementation produced 0.789886 instead. We revised that test expectation rather than weakening the prewritten 0.80 threshold. The stack differs from the course's recommended Groq SDK: this implementation uses a standard-library REST adapter and offline discourse detection so the backend can be demonstrated without credentials. The two-signal offline option was explicitly specified before implementation.

A concrete implementation divergence is that the planned submission response listed decision metadata, while the implementation additionally returns and persists the original `text` in both content records and audit events. This gives a reviewer the exact passage that produced a contested decision without asking the creator to resubmit it. The tradeoff is storing creative work in logs and larger records; production would need authorized reviewer access and a retention policy. The original plan has been retained so this change remains visible.

## AI usage

1. The assignment and prewritten architecture/detection contract directed Codex to produce a Flask API, detection functions, and SQLite storage. The result included inspectable signal metrics and optional provider support. During the rubric review, the generated provider adapter was revised: it previously coerced any explanation value to a string and accepted missing explanations as an empty string. It now requires a nonempty string explanation alongside a valid score; malformed responses force uncertainty. A new mocked-provider test checks absent, blank, and object-valued explanations plus a valid response. This overrides the generated adapter's permissive parsing so an opaque score is not treated as a usable assessment.
2. The labels, appeals, and uncertainty contract directed Codex to generate verification and documentation. Its initial test required the course AI-style passage to receive `likely_ai`. After the real score was inspected, that expectation was overridden to preserve the specification. A separate explicitly synthetic uniform paragraph was added to check reachability. The resulting evidence is local heuristic evidence; no live provider success or calibrated accuracy is claimed.

These are records of AI-assisted work in this session, not a claim that the student independently authored or validated it. Review and personalize this section before submission if required by your course.

## Submission and walkthrough

The source, plan, and evidence are ready for review. [walkthrough.md](walkthrough.md) gives a two-minute recording script and demonstration sequence. A walkthrough video has **not** been recorded. Commit and push the reviewed repository, record your tour, and submit the repository link plus video through the Course Portal. The supplied 25-point rubric is mapped to source and evidence in [rubric-check.md](rubric-check.md). This is a readiness review, not an awarded grade.
