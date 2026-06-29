# Provenance Guard

A backend system for creative-sharing platforms that analyzes submitted text and
returns an attribution result, a confidence score, and a reader-facing
transparency label. The goal is **not** perfect AI detection — it is to
communicate uncertainty honestly, protect human creators from false accusations,
and give creators a way to appeal disputed results.

See [planning.md](planning.md) for the full design rationale.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
```

Create a `.env` file with your Groq API key:

```
GROQ_API_KEY="gsk_..."
```

Run the server:

```bash
python app.py        # serves on http://localhost:5000
```

## Architecture

A submission flows through two independent detection signals, a confidence
scoring engine, a transparency-label generator, and the audit log:

```
POST /submit
   -> Signal 1: LLM classification (Groq)
   -> Signal 2: Stylometric heuristics
   -> Confidence scoring engine (combines both)
   -> Transparency label generator
   -> Audit log (structured JSON)
   -> API response
```

## API

| Method | Route | Purpose |
|--------|-------|---------|
| `GET`  | `/health` | Liveness check |
| `POST` | `/submit` | Analyze text; returns attribution, confidence, and label |
| `POST` | `/appeal` | Dispute a result; flips status to `under_review` |
| `GET`  | `/log` | View recent audit entries (no auth — for documentation/grading) |

### `POST /submit`

Body: `{"text": "...", "creator_id": "..."}` (both required, non-empty).

```bash
curl -s -X POST http://localhost:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "...", "creator_id": "test-user-1"}' | python -m json.tool
```

Returns `content_id`, `attribution`, `confidence`, `final_ai_score`,
`llm_score`, `stylometric_score`, the transparency `label`, and the full
per-signal output. **Save the `content_id`** to file an appeal later.

### `POST /appeal`

Body: `{"content_id": "...", "creator_reasoning": "..."}` (both required).

```bash
curl -s -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-CONTENT-ID", "creator_reasoning": "I wrote this myself..."}' | python -m json.tool
```

Finds the original decision, flips its status to `under_review`, logs the appeal
alongside the original classification, and returns confirmation. Re-classification
is **not** automated — a human reviewer makes the final call.

## Detection signals

**Signal 1 — LLM classification (Groq).** Judges the writing as a whole (tone,
flow, polish, generic vs. personal) and returns an `aiScore` in `[0, 1]`.

**Signal 2 — Stylometric heuristics.** Measures average word length, sentence
length variance, type-token ratio, punctuation density, and average sentence
length.

> **Calibration note:** the intuitive "uniform sentences = AI" heuristic *fails*
> on real samples — a formal *human* paragraph is often more uniform and has
> longer sentences than actual AI text, and type-token ratio is ~0.87 for every
> short sample (no signal). Average word length was the only metric that ordered
> samples sensibly, so it drives ~80% of the stylometric score. As a result this
> signal **cannot** reliably separate AI from polished formal human writing — the
> documented blind spot. The combined scoring relies on the LLM signal plus the
> false-positive-avoiding thresholds to handle it.

## Confidence scoring

```
finalAiScore   = (llmAiScore + stylometricAiScore) / 2
finalHumanScore = 1 - finalAiScore
```

| Result | Rule |
|--------|------|
| `high_confidence_ai` | `finalAiScore >= 0.75` **AND** both signals `>= 0.65` |
| `high_confidence_human` | `finalAiScore <= 0.25` **AND** both signals `<= 0.35` |
| `uncertain` | anything else |

Requiring **both** signals to agree before a high-confidence label is the core
false-positive defense: wrongly accusing a human creator is treated as the more
harmful error. Confidence is reported as `max(finalAiScore, finalHumanScore)`.

### Scoring across the confidence range (4 test inputs)

| Input | llm | stylo | final | result |
|-------|-----|-------|-------|--------|
| Clearly AI (formal) | 0.80 | 0.71 | 0.76 | `high_confidence_ai` |
| Clearly human (casual) | 0.20 | 0.00 | 0.10 | `high_confidence_human` |
| Borderline formal-human | 0.70 | 0.71 | 0.70 | `uncertain` |
| Borderline edited-AI | 0.20 | 0.34 | 0.27 | `uncertain` |

The stylometric signal scores the AI text and the formal-human text almost
identically (0.71 each) — it can't tell them apart. The **LLM signal** (0.80 vs
0.70) plus the `final >= 0.75` threshold is what keeps the formal human out of a
false AI accusation.

## Transparency labels

The `label` returned by `/submit` varies by attribution result, with the
confidence interpolated as a percentage. All three variants are reachable:

- **`high_confidence_ai`** → "Likely AI-Generated: ... Confidence: 76%. ... Creators may appeal this decision."
- **`high_confidence_human`** → "Likely Human-Written: ... Confidence: 90%. ..."
- **`uncertain`** → "Unable to Determine: ... Confidence: 73%. No definitive attribution is being made."

## Rate limiting

Applied to `POST /submit` via Flask-Limiter (in-memory storage):

```
10 per minute; 100 per day   (per client IP)
```

**Reasoning.** A real creator submits their own work occasionally — a handful of
pieces in a sitting, with edits and re-submissions. **10 per minute** comfortably
covers that bursty human pattern (submit, tweak, resubmit) while stopping a
script from flooding the endpoint, where each call costs a paid LLM request.
**100 per day** caps sustained abuse from a single IP while still accommodating a
heavy legitimate day of editing. The limit is per-IP so one abuser cannot
degrade service for everyone.

### Evidence — 12 rapid requests (limit is 10/min)

```
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

The first 10 succeed; subsequent requests return `429 Too Many Requests`
("10 per 1 minute").

## Audit log

Every submission and every appeal writes a structured JSON entry (JSON Lines in
`data/audit_log.jsonl`, not console output). Each submission entry captures:
timestamp, content ID, creator ID, attribution result, confidence, **both**
individual signal scores, the combined `final_ai_score`, status, and whether an
appeal has been filed. View entries via `GET /log`.

### Sample log (3 submissions + 1 appeal)

```json
{
  "entries": [
    {
      "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
      "content_id": "content_72694f17be6c",
      "event": "appeal",
      "original_confidence": 0.76,
      "original_llm_score": 0.8,
      "original_result": "high_confidence_ai",
      "original_stylometric_score": 0.71,
      "status": "under_review",
      "timestamp": "2026-06-29T02:43:41.255Z"
    },
    {
      "appeal_filed": false,
      "attribution": "uncertain",
      "confidence": 0.73,
      "content_id": "content_e0f377dee5a0",
      "creator_id": "demo-user",
      "event": "submission",
      "final_ai_score": 0.27,
      "llm_score": 0.2,
      "status": "classified",
      "stylometric_score": 0.34,
      "timestamp": "2026-06-29T02:43:41.244Z"
    },
    {
      "appeal_filed": false,
      "attribution": "high_confidence_human",
      "confidence": 0.9,
      "content_id": "content_2e9de7aea0ca",
      "creator_id": "demo-user",
      "event": "submission",
      "final_ai_score": 0.1,
      "llm_score": 0.2,
      "status": "classified",
      "stylometric_score": 0.0,
      "timestamp": "2026-06-29T02:43:40.542Z"
    },
    {
      "appeal_filed": true,
      "attribution": "high_confidence_ai",
      "confidence": 0.76,
      "content_id": "content_72694f17be6c",
      "creator_id": "demo-user",
      "event": "submission",
      "final_ai_score": 0.76,
      "llm_score": 0.8,
      "status": "under_review",
      "stylometric_score": 0.71,
      "timestamp": "2026-06-29T02:43:39.902Z"
    }
  ]
}
```

Note the appealed submission (`content_72694f17be6c`) now shows
`"status": "under_review"` and `"appeal_filed": true`, and a separate `appeal`
entry records the `appeal_reasoning` alongside the original decision.

## Project layout

```
app.py                       Flask app: /submit, /appeal, /log, /health + rate limiting
scoring.py                   Confidence scoring engine (threshold logic)
labels.py                    Transparency label generation
audit_log.py                 Structured JSON-Lines audit log
signals/
  llm_signal.py              Signal 1: Groq LLM classification
  stylometric_signal.py      Signal 2: stylometric heuristics
data/audit_log.jsonl         Runtime audit log (generated)
```