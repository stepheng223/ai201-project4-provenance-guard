# Two-minute portfolio walkthrough

This is a recording guide, not a recorded video.

1. (0:00–0:20) Show planning.md's diagram. Explain that this is a local backend prototype that combines discourse and structural signals, preserves uncertainty, and lets creators appeal.
2. (0:20–0:45) Run `python app.py`. In another terminal submit text using the README curl example. Show the UUID, per-signal scores, exact label, and status. Explain that the strength index is not a proven authorship probability.
3. (0:45–1:10) Open evidence/examples.json. Compare the uniform synthetic paragraph (0.913396), casual account (0.153090), and formal passage (0.534512). Point out that the supplied AI-style paragraph stays uncertain instead of weakening the threshold.
4. (1:10–1:35) Copy the fresh content UUID into the README appeal request. Submit creator reasoning. Show `under_review`, then GET /log and point out separate original classification and appeal events.
5. (1:35–1:50) Run `python -m unittest -v`; show seven passing checks and evidence/rate-limit.txt's final two 429 responses.
6. (1:50–2:10) Explain limitations: formal human prose and repetitive poetry can confuse style detectors; creator IDs are not authentication; a real deployment needs calibration and access control. State that Groq is optional and live calls were not verified in this build.

Record your screen and your own explanation using your preferred recording tool, then attach the resulting video in the Course Portal alongside your GitHub URL. If you personalize the implementation, regenerate evidence before recording.
