# Provenance Guard

A backend system for creative-sharing platforms that analyzes submitted text and
returns an attribution result, a confidence score, and a reader-facing
transparency label. The goal is **not** perfect AI detection — it is to
communicate uncertainty honestly, protect human creators from false accusations,
and give creators a way to appeal disputed results.

See [planning.md](planning.md) for the full design rationale.

## Contents

- [Setup](#setup)
- [Architecture](#architecture)
- [API](#api)
- [Detection signals — and why these two](#detection-signals--and-why-these-two)
- [Confidence scoring — and why this approach](#confidence-scoring--and-why-this-approach)
- [Transparency labels (all three variants)](#transparency-labels-all-three-variants)
- [Rate limiting](#rate-limiting)
- [Audit log](#audit-log)
- [Known limitations](#known-limitations)
- [Spec reflection](#spec-reflection)
- [AI usage](#ai-usage)
- [Project layout](#project-layout)

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

Each stage is a separate module ([signals/](signals/), [scoring.py](scoring.py),
[labels.py](labels.py), [audit_log.py](audit_log.py)) so a signal or the scoring
rule can change without touching the others. The two signals are deliberately
**independent and different in kind** — one semantic, one statistical — so they
fail in different ways (see scoring rationale below).

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

## Detection signals — and why these two

**Signal 1 — LLM classification (Groq).** Sends the text to a Groq-hosted model
(`llama-3.3-70b-versatile`) with a prompt asking it to judge human vs. AI based
on the writing *as a whole* — tone, flow, polish, generic vs. personal — and
return a JSON `aiScore` in `[0, 1]`.

*Why an LLM:* AI-vs-human is fundamentally a **semantic, holistic** judgment. The
things that make text feel machine-generated (generic framing, even polish,
"It is important to note that…" hedging) are meaning-level patterns a statistical
counter can't see. The LLM is the only component that actually *reads* the text.
It is prompted to hedge toward 0.5 on short or unusual input rather than guess,
and it fails safe: any API/parse error returns a neutral 0.5 so an outage can
never produce a confident false accusation.

**Signal 2 — Stylometric heuristics.** Pure statistics, no model: average word
length, sentence-length variance, type-token ratio (vocabulary diversity),
punctuation density, and average sentence length.

*Why a second, statistical signal:* a single LLM judgment is a black box that can
be confidently wrong. A cheap, deterministic, fully-explainable second opinion
that fails *differently* lets the system require **agreement** before making a
strong claim — which is the whole false-positive defense. It also costs nothing
and runs offline.

> **Calibration finding (important).** The intuitive stylometric idea — "uniform,
> smooth sentences = AI" — turned out to be **wrong on real samples**. A formal
> *human* paragraph (academic economics) was *more* uniform (coefficient of
> variation 0.26) and had *longer* sentences than the actual AI text. Type-token
> ratio was ~0.87 for every short sample, carrying no signal at all. The only
> metric that ordered samples sensibly was **average word length**, so it drives
> ~80% of the stylometric score; the rest contribute lightly. The honest
> consequence: this signal **cannot** separate AI from polished formal human
> writing, and the combined scoring leans on the LLM plus the thresholds to cover
> that gap. (See [Known limitations](#known-limitations).)

**What I'd change for a real deployment:**
- Replace the hand-tuned stylometric constants (calibrated on a handful of
  samples) with thresholds learned from a labeled corpus, with per-genre
  calibration (poetry, code, academic, casual all behave differently).
- Add a third signal of a different kind — e.g. a perplexity/burstiness measure
  from a small local model — so no single failure mode dominates.
- Persist storage in a real database (the audit log is currently a JSON-Lines
  file) and add authentication to `/log`.

## Confidence scoring — and why this approach

```
finalAiScore   = (llmAiScore + stylometricAiScore) / 2
finalHumanScore = 1 - finalAiScore
```

| Result | Rule |
|--------|------|
| `high_confidence_ai` | `finalAiScore >= 0.75` **AND** both signals `>= 0.65` |
| `high_confidence_human` | `finalAiScore <= 0.25` **AND** both signals `<= 0.35` |
| `uncertain` | anything else |

*Why averaging plus an agreement gate, instead of "take the higher score":*
picking whichever score is higher manufactures false certainty — a `0.51` lean
would read as a verdict. Averaging keeps the combined score honest, and the
**both-signals-must-agree** gate means a single confident signal can never alone
produce a high-confidence label. This is deliberate asymmetry: wrongly labeling a
human's work as AI is the more harmful error (it accuses someone of dishonesty),
so the bar for *any* high-confidence label is high, and everything ambiguous
falls through to `uncertain`. Confidence is reported as
`max(finalAiScore, finalHumanScore)` — the strength of the lean — which
reproduces the worked examples in [planning.md](planning.md) exactly.

### Two example submissions (real scores from testing)

**High-confidence case** — clearly casual human writing:

> "ok so i finally tried that new ramen place downtown and honestly?
> underwhelming. the broth was fine but they put WAY too much sodium in it…"

| llm_score | stylometric_score | final_ai_score | confidence | result |
|-----------|-------------------|----------------|------------|--------|
| 0.20 | 0.00 | 0.10 | **0.90** | `high_confidence_human` |

**Lower-confidence case** — formal human writing (academic economics):

> "The relationship between monetary policy and asset price inflation has been
> extensively studied in the literature. Central banks face a fundamental
> tension between their mandate for price stability…"

| llm_score | stylometric_score | final_ai_score | confidence | result |
|-----------|-------------------|----------------|------------|--------|
| 0.70 | 0.71 | 0.70 | **0.70** | `uncertain` |

The confidence moves meaningfully (0.90 vs 0.70) and the labels differ — the
scoring is not a constant. The second case is exactly where the design earns its
keep: both signals lean AI, but because the combined score doesn't clear 0.75 the
system refuses to accuse a human writer and returns `uncertain`.

### Full scoring sweep (4 inputs)

| Input | llm | stylo | final | result |
|-------|-----|-------|-------|--------|
| Clearly AI (formal) | 0.80 | 0.71 | 0.76 | `high_confidence_ai` |
| Clearly human (casual) | 0.20 | 0.00 | 0.10 | `high_confidence_human` |
| Borderline formal-human | 0.70 | 0.71 | 0.70 | `uncertain` |
| Borderline edited-AI | 0.20 | 0.34 | 0.27 | `uncertain` |

Note that the stylometric signal scores the AI text and the formal-human text
*identically* (0.71 each) — it genuinely can't tell them apart. The **LLM**
(0.80 vs 0.70) plus the `final >= 0.75` threshold is what keeps the formal human
out of a false AI accusation.

## Transparency labels (all three variants)

The `label` returned by `/submit` is generated by
[`generate_label()`](labels.py) and changes with the attribution result; the
confidence is interpolated as a whole-number percent. The exact text of each
variant:

**`high_confidence_ai`:**

> Likely AI-Generated: Our analysis found strong evidence that this content was
> generated by AI. Confidence: {confidence}%. This result is based on automated
> analysis and may not be perfect. Creators may appeal this decision.

**`high_confidence_human`:**

> Likely Human-Written: Our analysis found strong evidence that this content was
> written by a person. Confidence: {confidence}%. This result is based on
> automated analysis and may not be perfect.

**`uncertain`:**

> Unable to Determine: Our analysis could not confidently determine whether this
> content was written by a person or generated by AI. Confidence: {confidence}%.
> No definitive attribution is being made.

`{confidence}` is replaced with the actual value (e.g. `76`). Every label states
that the result is automated and may be imperfect; only the AI variant invites an
appeal, since that is the result that can damage a creator.

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

## Known limitations

**Formal writing by non-native English speakers is the system's worst case.**
This is not a generic "needs more data" gap — it is a direct consequence of how
the signals work:

- The **stylometric signal is ~80% driven by average word length**, because that
  was the only metric that discriminated on test samples. Dense, formal prose —
  long words, long sentences — scores high on stylometrics *regardless of author*.
  In testing it scored a formal human paragraph (0.71) **identically** to actual
  AI text (0.71).
- That leaves the **LLM signal as the only thing** separating formal humans from
  AI. But formal, polished, grammatically uniform writing is exactly the style
  LLMs are most likely to read as machine-generated — and non-native speakers
  often write *more* formally, not less.

So a non-native English speaker submitting careful, formal prose can have *both*
signals lean AI. The agreement-gate + `0.75` threshold usually catches this and
returns `uncertain` (as in the example above), but a slightly stronger LLM lean
would tip it into a false `high_confidence_ai` — the most harmful error the system
can make, against exactly the population least able to contest it.

Secondary weak spots, same root cause (statistics without meaning): **very short
text** (1–2 sentences give the stylometric signal almost nothing to measure) and
**repetitive poetry** (intentional repetition reads as AI-like uniformity).

## Spec reflection

**How the spec helped.** The confidence-scoring section gave concrete thresholds
*and three fully worked numeric examples* (`0.84 / 0.84 / 0.59`). That turned
"is the scoring correct?" into an objective test: I ran my engine against those
exact inputs and confirmed the results matched before wiring anything in. Without
those worked examples I would have had no way to catch a scoring function that
*looked* reasonable but silently used the wrong threshold — which is precisely the
failure the milestone warned about.

**How the implementation diverged, and why.** The spec describes the stylometric
signal as measuring sentence-length variance, type-token ratio, and sentence
uniformity, with the premise "AI = smoother, more uniform structure." When I
implemented and *tested* that, it scored clearly-AI text as human (0.20) and would
have flagged formal humans as the most AI-like of all. The premise didn't hold on
real samples. I diverged by making **average word length** the primary driver and
demoting the spec's metrics to light/reported-only roles. I kept the spec's
*intent* (a cheap statistical second opinion) but changed the *mechanism* because
the evidence contradicted the design. (A smaller divergence: the appeal endpoint
takes `creator_reasoning` per the Milestone 5 task rather than the spec's older
`appealType`/`reason` shape.)

## AI usage

I used Claude (via Claude Code) as the AI tool throughout. Three specific
instances where I directed it, reviewed the output, and revised:

1. **Second signal + scoring engine.** I gave it the detection-signals,
   uncertainty, and architecture sections and asked for the stylometric function
   and the combining logic. The **scoring** it produced matched the spec's worked
   examples on the first try (I verified all three). The **stylometric** function,
   however, implemented the intuitive "uniform sentences = AI" heuristic — which
   silently miscalibrated: my clearly-AI test input scored 0.20 (read as human).
   I **overrode** it: I had it dump the raw metrics for all four test inputs,
   discovered TTR was flat (~0.87) and sentence-uniformity was *inverted* on
   formal humans, and rebuilt the score around average word length. This is the
   single most important revision in the project.

2. **Transparency label function + appeal endpoint.** I asked it to generate the
   label generator and `POST /appeal` from the spec's label table and appeals
   workflow. I **verified** the three generated label strings matched
   [planning.md](planning.md) verbatim and confirmed the appeal flow updated
   status to `under_review` and logged the original decision before accepting it.
   I directed a change so the appeal also flips the *original* submission entry's
   status (not just appending a new entry), so `GET /log` reflects the dispute on
   the record it refers to.

3. **Flask skeleton + first signal.** It generated the initial app and the Groq
   signal, including a fail-safe (neutral 0.5 on any API error) that I kept
   because it aligns with the false-positive-avoiding design. I **overrode** its
   initial camelCase response keys (`contentId`) in favor of snake_case
   (`content_id`) to match the grading schema and the audit-log format.

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