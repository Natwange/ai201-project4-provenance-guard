"""Provenance Guard — Flask application.

M3 scope: the submission endpoint and the first detection signal (LLM-based
classification). Later milestones add the stylometric signal, confidence
scoring, transparency labels, the audit log, and the appeal endpoint.
"""

import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from audit_log import get_log, write_entry
from signals import analyze_llm_signal

load_dotenv()

app = Flask(__name__)


def interim_attribution(ai_score):
    """Provisional attribution based on signal 1 alone.

    This is a simple lean, NOT the final decision logic. Milestone 4 replaces
    it with the real engine (high_confidence_ai / high_confidence_human /
    uncertain) once the stylometric signal and combined scoring exist.
    """
    return "likely_ai" if ai_score >= 0.5 else "likely_human"


@app.get("/health")
def health():
    """Simple liveness check."""
    return jsonify({"status": "ok"})


@app.post("/submit")
def submit():
    """Accept raw text, run the first detection signal, and return a result.

    The first signal (LLM-based classification) is wired in and every call
    writes a structured entry to the audit log. The ``attribution`` and
    ``confidence`` values here are interim (derived from signal 1 alone); the
    real scoring engine and transparency label arrive in M4/M5.

    Request body (JSON):
        {"text": "<the writing to analyze>", "creator_id": "<id>"}

    Response (200):
        {
            "content_id": "content_...",  # unique; used by the appeal endpoint
            "creator_id": "<id>",
            "status": "classified",
            "attribution": "likely_ai" | "likely_human",  # interim
            "confidence": 0.0-1.0,        # interim, from signal 1 only
            "llm_score": 0.0-1.0,
            "label": "...",               # placeholder until M5 labels
            "signals": {"llm": { ...full signal 1 output... }}
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

    llm_result = analyze_llm_signal(text)
    llm_score = llm_result["aiScore"]

    # Interim attribution/confidence from signal 1 only (M4 replaces this).
    attribution = interim_attribution(llm_score)
    confidence = round(max(llm_score, 1 - llm_score), 2)

    # Structured audit entry — timestamp is added by write_entry().
    write_entry(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "attribution": attribution,
            "confidence": confidence,
            "llm_score": llm_score,
            "status": "classified",
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "status": "classified",
            "attribution": attribution,
            "confidence": confidence,
            "llm_score": llm_score,
            # Placeholder until the transparency-label generator lands (M5).
            "label": "Attribution interim — final label generated in M5.",
            "signals": {"llm": llm_result},
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