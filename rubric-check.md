# Required-rubric evidence map

Reviewed against the supplied 25-point rubric. This maps evidence to criteria; it does not guarantee a grade. README AI-usage descriptions record actual agent work and still need the student's own review and accurate account of their decisions.

| Criterion | Points available | Evidence |
| --- | ---: | --- |
| Text endpoint returns structured JSON | 1 | `app.py`: POST /submit; `evidence/examples.json`: five actual responses |
| Attribution and confidence in response | 1 | Every example response contains `attribution` and `confidence` |
| Label text in response | 1 | Every example response contains full `label` |
| Two signals, properties and blind spots | 1 | README: Detection signals and their limits |
| Both signals visible in results | 1 | Each example's `signals` array contains discourse and stylometry scores/metrics |
| High and lower confidence submissions | 1 | Synthetic: 0.913396; formal passage: 0.534512 |
| Combination and meaningful-score validation explained | 1 | README: Confidence scoring and validation; five contrasting fixtures and thresholds |
| Exact label text written out | 1 | README: Exact transparency labels table |
| Labels in plain language | 1 | All three labels describe authorship and uncertainty in reader-facing language |
| Label text changes by confidence category | 1 | examples.json includes likely_ai, likely_human, uncertain; tests compare exact labels |
| Appeal with creator reasoning | 1 | `test_app.py`: appeal test; audit sample's appeal_reasoning |
| Under-review status and audit visibility | 1 | Appeal event has status `under_review`; persistence test checks current record |
| Rate limiting demonstrated | 1 | `evidence/rate-limit.txt`: ten 200 responses then two 429 responses; middleware test |
| Specific limits and usage rationale | 1 | README: Rate limiting; app.py: 10/minute, 100/day |
| At least three entries with result, confidence, timestamp | 1 | `evidence/audit-sample.json`: six complete events |
| Structured log | 1 | SQLite stores JSON events; committed evidence is formatted JSON |
| Appeal alongside original event | 1 | Match appeal content_id to original classification event in audit sample |
| Planning describes signals and combination | 1 | planning.md: Detection signals and Uncertainty representation |
| Planning defines uncertainty ranges | 1 | planning.md: 0.80 / 0.30 thresholds and abstention rules |
| Planning writes all three labels | 1 | planning.md: Transparency labels |
| Planning includes appeals, edge cases, AI plan inputs | 1 | planning.md: API and appeals workflow, Anticipated edge cases, AI Tool Plan and diagram |
| Specific limitations tied to signals | 1 | README: formal essays, repetitive poetry, multilingual writing and metric limitations |
| Substantive spec reflection | 1 | README: planned metadata response expanded to include/store raw text for review; tradeoff explained |
| Two specific AI-use instances and outputs | 1 | README: AI usage, instances 1 and 2 |
| Revisions/overrides for each instance | 1 | Instance 1: provider explanation parsing tightened; instance 2: incorrect label test expectation overridden. These are agent revisions; student review remains necessary to support the rubric's student-decision wording. |

## Stretch scope

No bonus features are claimed (0/4 bonus implemented). The offline/Groq alternatives are one interchangeable discourse signal, not a three-signal ensemble. GET /log is an audit view, not an analytics dashboard. The human label is not a verified-human certificate. The API accepts text only.

## Remaining submission work

- Review the implementation and AI usage section; accurately describe your own decisions without claiming agent decisions as yours.
- Record the portfolio walkthrough using walkthrough.md.
- Commit and push the reviewed files to GitHub and submit the repository URL and video through the Course Portal.
- Live Groq success is unverified; default offline mode is the tested demonstration path.
