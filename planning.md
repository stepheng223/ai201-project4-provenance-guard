# Provenance Guard implementation plan

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
