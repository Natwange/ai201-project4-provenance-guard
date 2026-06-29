"""Provenance Guard — Flask application.

The submission endpoint runs both detection signals (LLM classification +
stylometric heuristics), combines them with the confidence scoring engine,
generates a transparency label, and writes a structured audit entry per call.
The appeal endpoint lets creators dispute a result, and rate limiting protects
the submission endpoint from abuse.
"""

import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit_log import find_submission, get_log, set_status, write_entry
from labels import generate_label
from scoring import combine_scores
from signals import analyze_llm_signal, analyze_stylometric_signal

load_dotenv()

app = Flask(__name__)

# Rate limiter — in-memory storage for local/dev use. Limits are applied
# per-endpoint (see /submit); no global default limit.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.get("/health")
def health():
    """Simple liveness check."""
    return jsonify({"status": "ok"})


@app.post("/submit")
@limiter.limit("10 per minute;100 per day")
def submit():
    """Accept raw text, run both detection signals, and return a scored result.

    Both signals (LLM classification + stylometric heuristics) run, the scoring
    engine combines them per planning.md, a transparency label is generated, and
    every call writes a structured audit entry recording both individual signal
    scores and the combined result. Rate limited to 10/min, 100/day per IP.

    Request body (JSON):
        {"text": "<the writing to analyze>", "creator_id": "<id>"}

    Response (200):
        {
            "content_id": "content_...",  # unique; used by the appeal endpoint
            "creator_id": "<id>",
            "status": "classified",
            "attribution": "high_confidence_ai" | "high_confidence_human"
                           | "uncertain",
            "confidence": 0.0-1.0,
            "final_ai_score": 0.0-1.0,
            "llm_score": 0.0-1.0,
            "stylometric_score": 0.0-1.0,
            "label": "<reader-facing transparency label>",
            "signals": {"llm": {...}, "stylometric": {...}}
        }
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Field 'text' is required and must be non-empty."}), 400

    creator_id = data.get("creator_id")
    if not isinstance(creator_id, str) or not creator_id.strip():
        return jsonify({"error": "Field 'creator_id' is required and must be non-empty."}), 400

    # Unique ID for this submission — the appeal endpoint and audit log key on it.
    content_id = f"content_{uuid.uuid4().hex[:12]}"

    # Run both detection signals and combine them per the scoring spec.
    llm_result = analyze_llm_signal(text)
    stylometric_result = analyze_stylometric_signal(text)
    llm_score = llm_result["aiScore"]
    stylometric_score = stylometric_result["aiScore"]

    score = combine_scores(llm_score, stylometric_score)
    label = generate_label(score["result"], score["confidence"])

    # Structured audit entry — records both signal scores + the combined result.
    write_entry(
        {
            "event": "submission",
            "content_id": content_id,
            "creator_id": creator_id,
            "attribution": score["result"],
            "confidence": score["confidence"],
            "final_ai_score": score["finalAiScore"],
            "llm_score": llm_score,
            "stylometric_score": stylometric_score,
            "status": "classified",
            "appeal_filed": False,
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "status": "classified",
            "attribution": score["result"],
            "confidence": score["confidence"],
            "final_ai_score": score["finalAiScore"],
            "llm_score": llm_score,
            "stylometric_score": stylometric_score,
            "label": label,
            "signals": {"llm": llm_result, "stylometric": stylometric_result},
        }
    )


@app.post("/appeal")
def appeal():
    """Accept a creator's appeal against an attribution decision.

    Finds the original classification, flips its status to ``under_review``,
    logs the appeal alongside the original decision, and returns confirmation.
    Re-classification is intentionally NOT automated — a human reviews it.

    Request body (JSON):
        {"content_id": "content_...", "creator_reasoning": "<why they disagree>"}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    content_id = data.get("content_id")
    if not isinstance(content_id, str) or not content_id.strip():
        return jsonify({"error": "Field 'content_id' is required and must be non-empty."}), 400

    creator_reasoning = data.get("creator_reasoning")
    if not isinstance(creator_reasoning, str) or not creator_reasoning.strip():
        return jsonify({"error": "Field 'creator_reasoning' is required and must be non-empty."}), 400

    original = find_submission(content_id)
    if original is None:
        return jsonify({"error": f"No submission found for content_id '{content_id}'."}), 404

    new_status = "under_review"

    # Flip the original submission's status and mark that an appeal was filed.
    set_status(content_id, new_status, extra={"appeal_filed": True})

    # Log the appeal alongside the original classification decision.
    appeal_entry = write_entry(
        {
            "event": "appeal",
            "content_id": content_id,
            "appeal_reasoning": creator_reasoning,
            "original_result": original.get("attribution"),
            "original_confidence": original.get("confidence"),
            "original_llm_score": original.get("llm_score"),
            "original_stylometric_score": original.get("stylometric_score"),
            "status": new_status,
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "status": new_status,
            "message": "Appeal received. This submission is now under review.",
            "appeal_reasoning": creator_reasoning,
            "original_result": original.get("attribution"),
            "original_confidence": original.get("confidence"),
            "timestamp": appeal_entry["timestamp"],
        }
    )


@app.get("/log")
def view_log():
    """Return the most recent audit log entries as JSON.

    No auth — this exists for documentation and grading visibility only.
    """
    return jsonify({"entries": get_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
