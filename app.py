"""Provenance Guard — Flask application.

Current scope: the submission endpoint runs both detection signals (LLM-based
classification + stylometric heuristics), combines them with the confidence
scoring engine, and writes a structured audit entry per call. Still to come:
the transparency-label generator and the appeal endpoint (M5).
"""

import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from audit_log import get_log, write_entry
from scoring import combine_scores
from signals import analyze_llm_signal, analyze_stylometric_signal

load_dotenv()

app = Flask(__name__)


@app.get("/health")
def health():
    """Simple liveness check."""
    return jsonify({"status": "ok"})


@app.post("/submit")
def submit():
    """Accept raw text, run both detection signals, and return a scored result.

    Both signals (LLM classification + stylometric heuristics) run, the scoring
    engine combines them per planning.md, and every call writes a structured
    audit entry recording both individual signal scores and the combined
    result. The transparency ``label`` is still a placeholder until M5.

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
            "label": "...",               # placeholder until M5 labels
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

    # Structured audit entry — records both signal scores + the combined result.
    write_entry(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "attribution": score["result"],
            "confidence": score["confidence"],
            "final_ai_score": score["finalAiScore"],
            "llm_score": llm_score,
            "stylometric_score": stylometric_score,
            "status": "classified",
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
            # Placeholder until the transparency-label generator lands (M5).
            "label": "Attribution complete — reader-facing label generated in M5.",
            "signals": {"llm": llm_result, "stylometric": stylometric_result},
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