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

The API validates JSON and applies submission limits before sending text to three measurement functions. Discourse, structural stylometry, and reference-overlap scores feed weighted scoring and uncertainty rules; the exact label and full signal output are saved with the content in a SQLite transaction. The response supplies a UUID for subsequent retrieval and appeals. An appeal checks the supplied creator ID, changes the content to `under_review`, and appends a new audit event while preserving the original decision. See [planning.md](planning.md) for the diagram and the specification written before implementation.

| Endpoint | Contract |
| --- | --- |
| `POST /submit` | `creator_id`, and `text` or structured `metadata`; returns ID, attribution, confidence, AI index, exact label, signals, timestamp, status |
| `POST /appeal` | `content_id`, `creator_id`, `creator_reasoning`; returns current record with `under_review` status |
| `GET /content/<id>` | Current stored decision and appeal state; 404 if missing |
| `GET /log` | Most recent 100 structured audit events, newest first |
| `GET /health` | JSON health response |
| `POST /verification` | Content ID, creator ID, reasoning and timestamped draft history; requests reviewer verification |
| `GET /verification/<id>` | Reviewer-authorized inspection of submitted drafts |
| `POST /verification/<id>/review` | Reviewer-authorized approval/rejection with notes |
| `GET /content/<id>/view` | Reader view displaying attribution and any distinct verified-human credential |
| `GET /analytics` | Detection patterns, appeal rate, mean confidence and content-type/credential counts |
| `GET /dashboard` | Responsive analytics view |

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

**Lexical discourse:** measures stock transitions/generic assertions (such as “it is important to note”) and conversational cues (such as “ok so”). Start at 0.5, add 0.12 per matched stock phrase, subtract 0.10 per conversational cue, and clamp to [0.05, 0.95]. These choices provide an inspectable discourse signal without API dependencies. They are hand-designed hypotheses, not validated linguistic evidence. Academic human prose can trigger stock phrases; AI can imitate casual language. Optional Groq replaces this function with a semantic assessment between 0 and 1; it does not add another signal to the ensemble.

**Stylometry:** measures sentence length coefficient of variation (CV), type-token ratio (TTR), and distinct punctuation types. Score = `0.65*(1-min(CV,1)) + 0.25*(1-TTR) + 0.10*(1-min(punctuation_types/5,1))`. Uniform sentence structure and repeated vocabulary increase the index. These are structural properties distinct from discourse phrases, although neither signal is statistically independent of writing style. Poetry, dialogue, punctuation conventions, and text length can distort these metrics.

**Reference matching (third signal):** measures the fraction of unique four-word sequences shared with a committed known-source passage in [reference_corpus.json](reference_corpus.json). The score is `0.5 + 0.45*coverage`. Unlike stock phrases or sentence statistics, it measures overlap with a particular source. An exact match yields 0.95; no match remains neutral at 0.50 rather than claiming human authorship. This small corpus contains an AI-assisted synthetic fixture from this project, not a representative or independently authenticated dataset. Legitimate quotation can match it; novel or paraphrased AI text can evade it. It demonstrates an ensemble mechanism, not a validated detector.

## Confidence scoring and validation

**Three-signal ensemble:** `ai_score = 0.55*discourse + 0.30*stylometry + 0.15*reference_match`. At least 0.80 means `likely_ai`; at most 0.30 means `likely_human`; everything between is `uncertain`. The higher AI threshold reflects the greater harm of accusing a human creator incorrectly. Fewer than 35 words, a maximum-minus-minimum spread greater than 0.50 across the three signals, or provider failure force uncertainty and constrain the index to [0.31, 0.79].

`confidence = max(ai_score, 1-ai_score)` expresses heuristic strength toward either end of the index. It is **not** the probability that the selected label is correct, especially for uncertain decisions; clients should display the plain-language label rather than a probability percentage. The API explicitly returns `confidence_kind=heuristic_strength_not_probability`. An AI index of 0.51 yields uncertainty, while 0.95 can yield likely AI when the ensemble supports it and sufficient text is present.

Actual offline endpoint results are in [evidence/examples.json](evidence/examples.json), including full input texts and per-signal measurements:

| Example | AI index | Confidence strength | Attribution |
| --- | ---: | ---: | --- |
| Deliberately uniform synthetic paragraph, beginning “Furthermore, stakeholders in modern society…” | 0.918625 | 0.918625 | likely_ai |
| Course AI-style paragraph, beginning “Artificial intelligence represents…” | 0.750322 | 0.750322 | uncertain |
| Casual ramen account, beginning “ok so i finally tried…” | 0.205863 | 0.794137 | likely_human |
| Formal monetary-policy paragraph | 0.529582 | 0.529582 | uncertain |
| Edited AI-style remote-work paragraph | 0.435194 | 0.564806 | uncertain |

The synthetic paragraph confirms the high-confidence category is reachable; the formal passage is a lower-confidence example. All four supplied examples were checked, with a fifth to demonstrate all labels. The supplied AI-style passage remains uncertain because it falls below the conservative threshold; the threshold was not lowered just to make that example pass. These style fixtures demonstrate score variation and rule behavior, **not empirical detection accuracy or calibration**. The course examples have no independently verified authorship. Deployment would require consented, held-out human and AI corpora, false-positive analysis across genres and writer populations, and calibration measurements.

## Exact transparency labels

| Attribution | Verbatim label |
| --- | --- |
| High-confidence AI | "Likely AI-generated. Multiple writing signals support this assessment, but it is not proof of authorship. The creator can appeal." |
| High-confidence human | "Likely human-written. Writing signals support human authorship, but this does not verify who wrote it." |
| Uncertain | "Authorship uncertain. The available writing signals are inconclusive; no reliable human or AI attribution can be made." |

## Appeals

Creators submit reasoning against a content ID with their matching creator ID. The transaction retains the original attribution, scores, and label, changes status to `under_review`, and appends an appeal event with `appeal_reasoning`, a new event timestamp, and the original timestamp. Reviewers can inspect `/log` alongside `/content/<id>`. A second appeal returns 409 and cannot overwrite the original reasoning. Unknown content and creator mismatch fail without modifying storage. Automated reassessment and reviewer resolution are outside this project's required scope.

Creator ID matching is a demonstration ownership check, not authentication: an attacker who knows an ID could impersonate its creator. Matching a creator ID alone does not earn a verified-human credential; the separate reviewer workflow below is required.

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
python test_stretch.py --evidence
```

Fourteen tests pass. They cover the five writing fixtures and exact label mapping; invalid submissions and short-text abstention; appeal ownership, missing IDs, duplicate appeals, original-event preservation, and persistence across app instances; 12-request rate-limit enforcement; threshold boundaries and disagreement; provider failure, malformed boolean scores, and missing or malformed provider explanations. Stretch tests additionally cover three-signal reference matching/conflict handling, reviewer authorization and approval/rejection, draft validation, certificate persistence and display, metadata validation/classification/appeals, and empty/populated analytics. Fixtures demonstrate local workflows; they do not represent independently verified human credentials. Evidence generation uses temporary databases and does not change your application database. Timestamps and UUIDs change on regeneration.

## Known limitations

Formal human essays can match stock phrases and uniform structure, causing false positives. Repetitive poetry can look generated because repeated words lower TTR; expressive AI writing can evade all three signals. English phrase matching is poorly suited to other languages. Naive sentence splitting mishandles abbreviations, and TTR is length-dependent. Provider prompts can be manipulated despite treating content as untrusted input. An LLM's self-reported score is also not calibrated.

This local prototype has public log/content endpoints, stores raw text and appeal reasoning, and lacks real authentication, retention rules, reviewer authorization, and a resolution endpoint for attribution appeals. Use only demonstration data. Production would require those controls, shared rate-limit storage, robust multilingual evaluation, and database operational safeguards. The four implemented stretch features are documented below.

## Spec reflection

Writing thresholds, verbatim labels, and duplicate-appeal behavior before implementation made it possible to assert endpoint behavior directly and keep original decisions intact. During the original two-signal build, the first scoring test assumed the course AI-style example would receive `likely_ai`; implementation produced 0.789886 instead (now 0.750322 under the three-signal ensemble). We revised that test expectation rather than weakening the prewritten 0.80 threshold. The stack differs from the course's recommended Groq SDK: this implementation uses a standard-library REST adapter and offline discourse detection so the backend can be demonstrated without credentials. The two-signal offline option was explicitly specified before implementation.

A concrete implementation divergence is that the planned submission response listed decision metadata, while the implementation additionally returns and persists the original `text` in both content records and audit events. This gives a reviewer the exact passage that produced a contested decision without asking the creator to resubmit it. The tradeoff is storing creative work in logs and larger records; production would need authorized reviewer access and a retention policy. The original plan has been retained so this change remains visible.

## AI usage

1. The assignment and prewritten architecture/detection contract directed Codex to produce a Flask API, detection functions, and SQLite storage. The result included inspectable signal metrics and optional provider support. During the rubric review, the generated provider adapter was revised: it previously coerced any explanation value to a string and accepted missing explanations as an empty string. It now requires a nonempty string explanation alongside a valid score; malformed responses force uncertainty. A new mocked-provider test checks absent, blank, and object-valued explanations plus a valid response. This overrides the generated adapter's permissive parsing so an opaque score is not treated as a usable assessment.
2. The labels, appeals, and uncertainty contract directed Codex to generate verification and documentation. Its initial test required the course AI-style passage to receive `likely_ai`. After the real score was inspected, that expectation was overridden to preserve the specification. A separate explicitly synthetic uniform paragraph was added to check reachability. The resulting evidence is local heuristic evidence; no live provider success or calibrated accuracy is claimed.

These are records of AI-assisted work in this session, not a claim that the student independently authored or validated it. Review and personalize this section before submission if required by your course.

## Stretch: ensemble detection

The text pipeline returns three distinct signal scores and explicit `signal_weights=[0.55,0.30,0.15]`. Discourse has the largest weight, structural metrics the next, and source overlap the smallest because the corpus is deliberately tiny. Conflicts (score spread >0.50) force an uncertain label rather than allowing a weighted majority to conceal disagreement. Short-text and unavailable-provider abstention rules remain in force. `evidence/stretch.json` includes all three scores and the ensemble result. The optional Groq signal still replaces discourse rather than increasing the count to four.

## Stretch: provenance certificate

A creator submits at least two distinct draft versions with increasing, timezone-aware timestamps and reasoning. The final draft must equal the existing submitted text and predate its submission; evidence is bounded to five drafts, each at most 20,000 characters. Verification requests are stored durably. Only a reviewer with the configured `REVIEWER_TOKEN` can inspect the drafts and approve/reject with nonempty review notes. Missing reviewer configuration returns 503; absent or incorrect credentials return 403. Repeated requests/reviews return 409.

The human reviewer must examine the drafts and reasoning before approving. Approval creates a certificate ID tied to the content ID, creator ID, verification ID, issuance time, and SHA-256 of the exact UTF-8 text. It appears in the content response as `certificate` and the separate `certificate_label`: **"Verified human — draft history reviewed"**. `/content/<id>/view` displays that credential alongside the unchanged automated attribution label. Rejection issues no credential. Request and review outcomes append audit events; verification does not automatically resolve appeals or change detector scores.

This certificate records a **human reviewer's attestation**, not proof that timestamps/drafts were authentic. Drafts are self-supplied and can be fabricated. Reviewers need external evidence or supervised writing when a platform requires stronger assurance. The token authorizes the local reviewer role; it is not a complete identity system. Certificates currently apply to text only, have no expiry/revocation flow, and are server-stored records rather than digitally signed portable credentials.

Set a private `REVIEWER_TOKEN` in `.env` before starting the app, then use this workflow with an existing submission:

```bash
# verification-request.json must contain real content_id and creator_id,
# creator_reasoning, and drafts: [{"text":"...", "timestamp":"...Z"}, ...].
curl -s http://127.0.0.1:5000/verification \
  -H 'Content-Type: application/json' --data-binary @verification-request.json

# Set REVIEWER_TOKEN in this terminal without committing it. Replace VERIFICATION_ID.
curl -s http://127.0.0.1:5000/verification/VERIFICATION_ID \
  -H "Authorization: Bearer $REVIEWER_TOKEN"

curl -s http://127.0.0.1:5000/verification/VERIFICATION_ID/review \
  -H "Authorization: Bearer $REVIEWER_TOKEN" -H 'Content-Type: application/json' \
  -d '{"approved":true,"review_notes":"I examined the submitted drafting history and supporting explanation."}'
```

[evidence/stretch.json](evidence/stretch.json) contains a complete synthetic request/approval flow. [evidence/verified-content.html](evidence/verified-content.html) is the real rendered reader view from that flow; the demo reviewer approval is test evidence, not independent human verification.

## Stretch: analytics dashboard

Open **http://127.0.0.1:5000/dashboard** while the app runs. The view shows detection counts/ratios (AI, human, uncertain), appeal rate, mean confidence strength, total submissions, content-type totals, and verified credential count. `/analytics` exposes the same metrics as JSON. Appeal rate counts appealed content divided by all stored submissions, not appeal events; mean confidence is the arithmetic mean of original decision strengths. Analytics query all current content records rather than the last 100 log events, so verification and appeals cannot inflate totals. Empty databases show zeros and a clear empty state.

The dashboard includes labeled proportions, accessible meters, responsive cards, and a refresh link. [evidence/dashboard.html](evidence/dashboard.html) is a rendered snapshot; tests verify the HTML and metrics, but browser visual inspection has not been performed. Metrics are heuristic outcomes, not accuracy measurements. Like the existing demo log, this local analytics view has no authentication.

## Stretch: structured metadata (second content type)

Submit `content_type="structured_metadata"` with a `metadata` object describing an image, audio, or video asset. This analyzes **structured metadata**, not pixels, audio samples, or prose flattened from the metadata. Text remains the default content type.

```bash
curl -s http://127.0.0.1:5000/submit \
  -H 'Content-Type: application/json' \
  -d '{"creator_id":"artist-1","content_type":"structured_metadata","metadata":{"asset_name":"Sunset cover illustration","media_type":"image","declared_origin":"ai","tools":["DALL-E 3"],"generator":"DALL-E 3","revisions":[]}}'
```

Three signals examine different properties:

| Metadata signal | Property and score | Weight |
| --- | --- | ---: |
| Origin declaration | `declared_origin=ai` yields 0.95; human/unknown stays neutral at 0.50 because self-claims are unverifiable | 0.45 |
| Generation-tool evidence | Known AI tool names or a nonempty generator declaration yield 0.95; absent evidence yields 0.50 | 0.35 |
| Revision history | At least 3 strictly ordered revisions yield 0.20; 2 yield 0.35; fewer yield 0.50 | 0.20 |

The same 0.80/0.30 thresholds and >0.50 conflict abstention apply. The example produces AI index **0.860000** and `likely_ai`; substantial editing history conflicting with AI declarations instead produces uncertainty. Human declarations and revisions alone remain uncertain and cannot earn a credential. Signals are self-reported metadata, so omitted tools, fabricated revisions, unknown generators, and ambiguous export histories can mislead them. A nonempty `generator` field is interpreted as a declaration of generation tooling, so ordinary editing applications belong in `tools` rather than `generator`.

Required metadata fields: `asset_name` (1–200 characters), `media_type` (image/audio/video), `declared_origin` (human/ai/unknown). Optional fields: `tools` (up to 20 nonempty names of at most 100 characters), `generator` (up to 100 characters), `revisions` (up to 20 objects containing a timezone-aware, nonfuture `timestamp` and a nonempty `summary` of at most 1,000 characters). Unknown fields, malformed types and unordered timestamps return 400. Metadata submissions use the existing rate limits, persistent storage, structured audit log, and appeal workflow.

Exact metadata labels:

| Attribution | Verbatim label |
| --- | --- |
| High-confidence AI | "Likely AI-generated based on the supplied provenance metadata. This assessment does not inspect the asset itself; the creator can appeal." |
| Human-supporting metadata | "Metadata supports human creation, but the supplied history and declarations do not verify authorship." |
| Uncertain | "Asset authorship uncertain. The supplied provenance metadata is inconclusive and has not been independently verified." |

The human-supporting variant is defined for completeness but cannot be reached using the conservative current metadata signals; self-reported metadata is intentionally insufficient for that verdict.

## Submission and walkthrough

The source, plan, and evidence are ready for review. [walkthrough.md](walkthrough.md) gives a roughly three-minute recording script and demonstration sequence. A walkthrough video has **not** been recorded. Commit and push the reviewed repository, record your tour, and submit the repository link plus video through the Course Portal. The supplied 25-point rubric is mapped to source and evidence in [rubric-check.md](rubric-check.md). This is a readiness review, not an awarded grade.
