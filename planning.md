# Provenance Guard implementation plan

The baseline plan below predates the required implementation. The later stretch plan records the four bonus features before their implementation; its three-signal weights supersede the original two-signal weights.

## Architecture
```text
POST /submit --validated text--> lexical/LLM signal --AI score-->
  stylometric signal --AI score--> weighted scoring --score/category-->
  transparency label --decision--> SQLite transaction --stored decision--> JSON response
POST /appeal --content ID, creator ID, reasoning--> ownership/existence check
  --accepted appeal--> SQLite status + immutable audit event --confirmation--> JSON response
GET /log --request--> SQLite audit events --JSON--> reviewer
```
A submission is validated and rate limited before detection. Two signals feed conservative scoring, then the decision and exact label are atomically stored; appeals preserve that original decision and add a review event.

## Detection signals
The first signal measures lexical/discourse cues: stock transitions and generic claims versus conversational markers. Its offline score is clamped to [0.05, 0.95], starting at 0.5, adding 0.12 per stock phrase and subtracting 0.10 per conversational cue. This captures discourse choices but misses original AI prose and can penalize formal human prose. Optional Groq mode replaces this signal with a structured semantic assessment; it does not count as an extra signal.
The second signal measures sentence length coefficient of variation, vocabulary repetition, and punctuation diversity. Its score is 0.65*(1-min(CV,1)) + 0.25*(1-type_token_ratio) + 0.10*(1-min(punctuation_types/5,1)). Uniform structure can resemble generated prose; poetry, non-native writing, and short samples violate this assumption. Both return a score and explanatory metrics.

## Uncertainty representation
The AI-likelihood index is 0.65*discourse + 0.35*stylometry. High-confidence AI requires index >=0.80; human requires <=0.30; otherwise uncertain. Fewer than 35 words, signal disagreement >0.50, or a failed LLM request force uncertain and pull the index into [0.31,0.79]. Confidence is max(index,1-index), a heuristic strength score, not an empirically calibrated probability. Thus an index of 0.6 means uncertain, not a claim that AI authored 60% of the text. False positives have the stricter threshold.

## Transparency labels
- AI: "Likely AI-generated. Multiple writing signals support this assessment, but it is not proof of authorship. The creator can appeal."
- Human: "Likely human-written. Writing signals support human authorship, but this does not verify who wrote it."
- Uncertain: "Authorship uncertain. The available writing signals are inconclusive; no reliable human or AI attribution can be made."

## API and appeals workflow
POST /submit accepts text (1–20,000 characters) and creator_id (1–100 characters); returns content_id, attribution, confidence, ai_score, label, signals, timestamp, status. POST /appeal accepts content_id, creator_id, creator_reasoning (1–4,000 characters). A matching creator ID is a demo ownership check, not authentication. Appeals update status to under_review and atomically append an audit event including original decision and reasoning. Missing IDs return 404, mismatched creators 403, repeated appeals 409. GET /content/<id> returns current state; GET /log returns up to 100 recent events. Reviewers see both signal scores, original attribution, reasoning, and timestamps. Automated resolution is out of scope.

## Anticipated edge cases
Formal human academic prose may resemble generic AI discourse: conservative thresholds and appeals reduce harm. Repetitive poetry and very short texts yield unreliable structure: short texts force uncertain, while poetry remains a documented limitation. Model timeouts or malformed scores must yield uncertainty, never a fabricated successful assessment. Duplicate appeals cannot overwrite the first reasoning.

## Production decisions
SQLite persists decisions and audit events in one transaction. Submission limits are 10/minute and 100/day per remote IP; reasonable revision bursts are allowed while automated flooding is curtailed. Memory storage is suitable for a single local process only; deploy with shared limiter storage and real identity/authentication. Logs contain submitted text and reasoning and require access control before deployment.

## AI Tool Plan
M3: provide detection/API sections and architecture to Codex; request Flask skeleton, lexical signal and optional Groq adapter. Verify validation, structured scores, and provider failure behavior.
M4: provide detection and uncertainty sections; request stylometric metrics and weighted scoring. Check four contrasting fixtures, boundary values, disagreement, and short-text abstention.
M5: provide exact labels and appeals workflow; request label mapping, transactional appeal storage, and limiter. Test all label variants, ownership, duplicate/missing appeals, audit persistence, and 429 responses.
No stretch features planned; prioritize required behavior and honest evidence.

## Stretch feature plan (before implementation)

### Ensemble detection
Add reference matching: four-word sequence overlap against a committed synthetic AI reference passage. Unlike discourse cues or sentence statistics this measures similarity to a known source. Score = 0.5 + 0.45*matched_ngram_fraction; absence of matches is neutral, never human evidence. Blind spots: tiny reference corpus, legitimate quotations and paraphrases. Combine discourse 0.55, stylometry 0.30, reference matching 0.15. Keep thresholds 0.80/0.30; >0.50 spread across available signals forces uncertainty. Return all scores and weights; metadata uses its own three signals. Regenerate evidence because scores change.

### Provenance certificate
A creator requests verification for a text content ID with at least two distinct, timestamped drafts, the final one matching the submission. Validate ordered timezone-aware timestamps, final text, ownership, and bounded evidence. A human reviewer inspects evidence using GET /verification/<id> and approves or rejects through POST /verification/<id>/review with a configured reviewer Bearer token and review notes. No automatic certificate award. Approval issues a UUID certificate bound to SHA-256 of the exact text and displays "Verified human — draft history reviewed" separately from the unchanged detection label. This demo records a reviewer's attestation, not cryptographic proof of the drafting process. Store requests/decisions durably and audit both; reject duplicate pending/completed requests. Missing reviewer configuration fails closed. Verification does not resolve an attribution appeal.

### Analytics dashboard
GET /analytics returns metrics derived from current content records, not audit events: attribution counts/ratios, appeal rate, mean confidence, content type counts and verified content count. Empty denominators return zero. GET /dashboard renders a responsive Flask/Jinja view with labeled verdict bars and metric cards. No external hosting or separate frontend service. Count each content item once even when it has multiple audit events.

### Multi-modal support
POST /submit accepts content_type=structured_metadata and metadata object rather than text. Metadata describes a creative asset: asset_name, media_type (image/audio/video), declared_origin (human/ai/unknown), tools (list), revisions (0–20 ordered timestamped objects with summary), and optional generator. Detect using three separate metadata properties: origin declaration, known generative-tool evidence, and revision-history depth. Scores: AI declaration .95, otherwise .5; AI tool/generator .95, otherwise .5; history 3+ revisions .20, two .35, fewer .5. Weights .45/.35/.20; conflicts >.50 force uncertainty; declaration and tool agreement can yield likely_ai. Unverified declarations alone cannot produce verified human. This analyzes metadata, not pixels/waveforms; return metadata-specific labels and metrics, store the original structured object, and support appeals. Reject malformed fields, excessive sizes, invalid media types and timestamps. Do not flatten metadata into prose for text detection.

### Stretch verification and AI tool plan
Give Codex this stretch plan and architecture before generation. Request ensemble matching, draft-review storage and endpoints, analytics query/view, and a separate metadata pipeline. Verify known-source overlap, conflict abstention, certificate authorization/final-text/timestamp/duplicate checks and persistence, analytics denominators, metadata validation/scoring/appeals, and default required-feature regression tests. Commit reproducible stretch JSON evidence and a dashboard HTML render; extend README and rubric map with exact workflows and limitations.
