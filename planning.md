# Provenance Guard Planning

## Project Overview

Provenance Guard is a backend system for creative sharing platforms. It analyzes submitted text and returns an attribution result, confidence score, and transparency label. The goal is not to perfectly detect AI writing, but to communicate uncertainty honestly, protect human creators from false accusations, and give creators a way to appeal disputed results.

## Detection Signals

### Signal 1: LLM-Based Classification

The LLM-based signal asks a Groq-powered model to judge whether the submitted writing appears human-written or AI-generated.

This signal measures the writing as a whole: tone, flow, organization, word choice, and whether the text feels overly generic, polished, repetitive, or naturally personal. In simple terms, it asks: “Does this writing read like something a person wrote, or does it read like AI-generated text?”

Expected output:

```json
{
  "signal": "llm",
  "aiScore": 0.82,
  "humanScore": 0.18,
  "reason": "The text is polished, generic, and has a highly uniform structure."
}
```

The `aiScore` is a number from `0` to `1`.

* `0.00` means strongly human.
* `0.50` means unclear.
* `1.00` means strongly AI-generated.

The `humanScore` is calculated as `1 - aiScore`.

Blind spot: The LLM can be wrong. It may misclassify skilled human writing as AI-generated, or heavily edited AI writing as human-written. It also may struggle with poetry, short text, non-standard grammar, or writing styles it has not seen often.

### Signal 2: Stylometric Heuristics

The stylometric signal uses measurable writing statistics instead of model judgment.

It measures structural properties such as:

* Sentence length variance
* Type-token ratio, meaning vocabulary diversity
* Punctuation density
* Average sentence complexity

This signal asks: “Do the measurable writing patterns look more human or more AI-generated?”

AI-generated text often has smoother, more uniform sentence structure. Human writing often has more variation, uneven rhythm, and more distinctive vocabulary choices.

Expected output:

```json
{
  "signal": "stylometric",
  "aiScore": 0.64,
  "humanScore": 0.36,
  "metrics": {
    "sentenceLengthVariance": 3.8,
    "typeTokenRatio": 0.41,
    "punctuationDensity": 0.06,
    "averageSentenceLength": 18.2
  }
}
```

Blind spot: Stylometric statistics do not understand meaning. A human poem with simple vocabulary and repetition may look AI-generated. A sophisticated AI-generated piece with varied sentence lengths and unusual word choices may look human-written.

## Confidence Scoring and Uncertainty

Each signal returns an `aiScore` between `0` and `1`.

The system calculates:

```txt
finalAiScore = (llmAiScore + stylometricAiScore) / 2
finalHumanScore = 1 - finalAiScore
```

The system does not simply choose whichever score is higher. That would create false certainty. For example, a `0.51` human score should not produce a strong human label because the system is barely leaning human.

### Thresholds

```txt
High-confidence AI:
finalAiScore >= 0.75
AND both signals have aiScore >= 0.65

High-confidence Human:
finalAiScore <= 0.25
AND both signals have aiScore <= 0.35

Uncertain:
Any result that does not meet the high-confidence AI or high-confidence human rules.
```

This means a confidence score around `0.60` is not treated as a strong conclusion. A `0.60` AI score means the system is leaning AI, but not strongly enough to make a confident attribution claim. The result should be labeled uncertain.

### Examples

Both signals agree AI:

```txt
LLM aiScore: 0.88
Stylometric aiScore: 0.80
Final aiScore: 0.84
Result: high_confidence_ai
Confidence: 0.84
```

Both signals agree human:

```txt
LLM aiScore: 0.12
Stylometric aiScore: 0.20
Final aiScore: 0.16
Final humanScore: 0.84
Result: high_confidence_human
Confidence: 0.84
```

Signals disagree:

```txt
LLM aiScore: 0.88
Stylometric aiScore: 0.30
Final aiScore: 0.59
Result: uncertain
Confidence: 0.59
```

The disagreement prevents a high-confidence label.

## Confidence Score Design

The confidence thresholds were intentionally chosen to reduce false positives, since incorrectly labeling a human creator's work as AI-generated is more harmful than failing to detect AI-generated content. A submission only receives a high-confidence AI label when both detection signals strongly agree (AI score ≥ 0.75). Likewise, a submission only receives a high-confidence human label when both signals strongly indicate human authorship (AI score ≤ 0.25). Any score between these thresholds is labeled Uncertain, reflecting that the evidence is mixed or insufficient to make a confident attribution.

## Transparency Label Design

The API will return one of three transparency labels.

| Result                | Label Text                                                                                                                                                                                                                        |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| High-confidence AI    | “Likely AI-Generated: Our analysis found strong evidence that this content was generated by AI. Confidence: {confidence}%. This result is based on automated analysis and may not be perfect. Creators may appeal this decision.” |
| High-confidence Human | “Likely Human-Written: Our analysis found strong evidence that this content was written by a person. Confidence: {confidence}%. This result is based on automated analysis and may not be perfect.”                               |
| Uncertain             | “Unable to Determine: Our analysis could not confidently determine whether this content was written by a person or generated by AI. Confidence: {confidence}%. No definitive attribution is being made.”                          |

## Appeals Workflow

A creator or reporter can submit an appeal if they disagree with the attribution result.

The appeal form should display:

```txt
Disagree with the result? Please submit an appeal below.
```

The user provides:

* `contentId`
* `appealType`
* `reason`

Appeal types:

```txt
creator_dispute: A creator says their human writing was incorrectly labeled as AI.
reader_report: A reader or user says content labeled human may actually be AI-generated.
```

When an appeal is submitted, the system:

1. Finds the original attribution decision.
2. Stores the appeal reason.
3. Updates the content status to `under_review`.
4. Logs the appeal in the audit log.
5. Returns a confirmation response.

Appeal request example:

```json
{
  "contentId": "content_123",
  "appealType": "creator_dispute",
  "reason": "I wrote this myself and can provide drafts showing my writing process."
}
```

Updated content status:

```json
{
  "contentId": "content_123",
  "status": "under_review"
}
```

Audit log appeal entry:

```json
{
  "eventType": "appeal_submitted",
  "contentId": "content_123",
  "appealType": "creator_dispute",
  "originalResult": "high_confidence_ai",
  "originalConfidence": 0.82,
  "newStatus": "under_review",
  "reason": "I wrote this myself and can provide drafts showing my writing process.",
  "timestamp": "2026-06-28T00:00:00Z"
}
```

A human reviewer opening the appeal queue should see:

* Content ID
* Original submitted text
* Original attribution result
* Original confidence score
* LLM signal score and reason
* Stylometric signal score and metrics
* User appeal reason
* Current status: `under_review`
* Timestamp of the original decision
* Timestamp of the appeal

The system does not automatically flip the label after an appeal. The original score remains in the audit log, and the status changes to `under_review`.

## False Positive Handling

A false positive happens when human-written content is incorrectly labeled as AI-generated. This is especially harmful because it can damage a creator’s reputation and make them feel accused of dishonesty.

To reduce this risk, the system only applies a high-confidence AI label when both detection signals strongly support that result. If one signal says AI but the other signal is weak or points human, the system returns `uncertain` instead.

Example:

```txt
LLM aiScore: 0.90
Stylometric aiScore: 0.38
Final aiScore: 0.64
Result: uncertain
```

Even though the LLM strongly suspects AI, the stylometric signal does not strongly agree. The system avoids making a strong AI accusation.

## Anticipated Edge Cases

### Edge Case 1: Repetitive poetry

A human-written poem may intentionally repeat words, phrases, or sentence structures for artistic effect. The stylometric signal may treat this repetition as AI-like because the writing appears uniform.

Example risk:

```txt
A poem repeats the same phrase at the end of every stanza.
```

Expected system behavior: If the LLM signal recognizes the creative style but the stylometric signal flags repetition, the final result should become uncertain rather than high-confidence AI.

### Edge Case 2: Short text submissions

Very short writing samples may not provide enough information for reliable analysis. A three-line poem, caption, or short paragraph may not have enough sentence variety or vocabulary diversity for the stylometric signal to be meaningful.

Expected system behavior: The system should avoid high-confidence labels for very short text and lean toward uncertain.

### Edge Case 3: Human-edited AI text

A user may generate text with AI and then heavily edit it. The writing may contain both AI-like and human-like signals.

Expected system behavior: If one signal points AI and another points human, the system should return uncertain and log both signal scores.

### Edge Case 4: Highly polished human writing

A skilled writer may produce clean, polished, grammatically consistent writing that resembles AI-generated text.

Expected system behavior: The system should require signal agreement before assigning a high-confidence AI label. If the evidence is mixed, the label should be uncertain.

## Architecture

### Submission Flow

```text
Creative Platform / Client
        |
        | raw text + creator/content metadata
        v
POST /submit
        |
        | raw text
        v
Rate Limiter
        |
        | accepted raw text
        v
LLM-Based Classification Signal
        |
        | llmLabel + llmAiScore + llmReason
        v
Stylometric Heuristics Signal
        |
        | sentence variance + vocabulary diversity + punctuation density + stylometricAiScore
        v
Confidence Scoring Engine
        |
        | combinedAiScore + signal agreement/disagreement
        v
Attribution Decision Engine
        |
        | attribution result: high_confidence_ai / high_confidence_human / uncertain
        v
Transparency Label Generator
        |
        | reader-facing label text
        v
Audit Log
        |
        | saved decision: raw signal scores + combined score + label + timestamp
        v
API Response
        |
        | contentId + attribution result + confidence score + label text + status
        v
Creative Platform / Client
```

### Appeal Flow

```text
Creator / Reporter
        |
        | contentId + appeal reason + appeal type
        v
POST /appeal
        |
        | appeal request
        v
Find Original Decision
        |
        | original attribution + original confidence + original signal scores
        v
Status Update
        |
        | status changed to under_review
        v
Audit Log
        |
        | saved appeal event: reason + previous status + new status + timestamp
        v
API Response
        |
        | contentId + status: under_review + appeal confirmation
        v
Creator / Reporter
```

The submission flow accepts raw text, runs it through both detection signals, combines the signal scores into a confidence score, creates a transparency label, writes the decision to the audit log, and returns a structured API response. The appeal flow accepts a dispute reason, finds the original decision, updates the content status to `under_review`, logs the appeal, and returns confirmation to the user.

## AI Tool Plan

### M3: Submission Endpoint + First Signal

Spec sections to provide to the AI tool:

* Project Overview
* Detection Signals
* Architecture

Ask the AI tool to generate:

* A Flask app skeleton
* A `POST /submit` endpoint
* Request validation for submitted text
* A first version of the LLM-based signal function
* A basic response structure containing `contentId`, `status`, and the LLM signal output

Verification steps:

* Test the endpoint with a clearly AI-generated paragraph.
* Test the endpoint with a clearly human-sounding paragraph.
* Confirm the endpoint rejects missing or empty text.
* Confirm the LLM signal returns an `aiScore`, `humanScore`, and `reason`.

### M4: Second Signal + Confidence Scoring

Spec sections to provide to the AI tool:

* Detection Signals
* Confidence Scoring and Uncertainty
* False Positive Handling
* Architecture

Ask the AI tool to generate:

* A stylometric heuristic function
* Sentence length variance calculation
* Type-token ratio calculation
* Punctuation density calculation
* Average sentence length calculation
* Final scoring logic that combines the LLM score and stylometric score
* Decision logic for `high_confidence_ai`, `high_confidence_human`, and `uncertain`

Verification steps:

* Test a clearly AI-like sample and confirm the AI score is higher.
* Test a more personal human-like sample and confirm the human score is higher.
* Test a mixed sample and confirm the result becomes uncertain.
* Confirm a `0.60` leaning score does not become a high-confidence label.

### M5: Production Layer

Spec sections to provide to the AI tool:

* Transparency Label Design
* Appeals Workflow
* Anticipated Edge Cases
* Architecture

Ask the AI tool to generate:

* Transparency label generation logic
* Audit log writing for every attribution decision
* `POST /appeal` endpoint
* Appeal status update logic
* `GET /log` endpoint to view audit entries
* Basic rate limiting for `POST /submit`

Verification steps:

* Confirm all three label variants are reachable.
* Confirm every submission creates an audit log entry.
* Confirm an appeal updates status to `under_review`.
* Confirm the appeal is added to the audit log.
* Confirm rate limiting blocks repeated submissions after the configured limit.

## Stretch Feature Rule

Before starting any stretch feature, this planning document must be updated with:

* What feature is being added
* Why it improves the system
* What endpoints or files will change
* How the feature will be tested
