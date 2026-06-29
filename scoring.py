"""Confidence scoring engine.

Combines the two detection signals into a single attribution decision,
following the thresholds defined in planning.md exactly:

    finalAiScore   = (llmAiScore + stylometricAiScore) / 2
    finalHumanScore = 1 - finalAiScore

    high_confidence_ai:    finalAiScore >= 0.75 AND both signals aiScore >= 0.65
    high_confidence_human: finalAiScore <= 0.25 AND both signals aiScore <= 0.35
    uncertain:             anything else

The system deliberately does NOT label by whichever score is merely higher.
Requiring agreement from both signals reduces false positives — wrongly
accusing a human creator is treated as the more harmful error.

Confidence reports the strength of the lean, max(finalAiScore, finalHumanScore),
matching all three worked examples in planning.md (0.84, 0.84, 0.59).
"""

# Threshold constants, straight from planning.md.
HIGH_AI_FINAL = 0.75
HIGH_AI_SIGNAL = 0.65
HIGH_HUMAN_FINAL = 0.25
HIGH_HUMAN_SIGNAL = 0.35


def combine_scores(llm_ai_score, stylometric_ai_score):
    """Combine two signal aiScores into an attribution decision.

    Args:
        llm_ai_score: aiScore (0..1) from the LLM signal.
        stylometric_ai_score: aiScore (0..1) from the stylometric signal.

    Returns:
        {
            "result": "high_confidence_ai" | "high_confidence_human" | "uncertain",
            "finalAiScore": float,
            "finalHumanScore": float,
            "confidence": float,
        }
    """
    final_ai = (llm_ai_score + stylometric_ai_score) / 2
    final_human = 1 - final_ai

    both_high_ai = llm_ai_score >= HIGH_AI_SIGNAL and stylometric_ai_score >= HIGH_AI_SIGNAL
    both_low_ai = llm_ai_score <= HIGH_HUMAN_SIGNAL and stylometric_ai_score <= HIGH_HUMAN_SIGNAL

    if final_ai >= HIGH_AI_FINAL and both_high_ai:
        result = "high_confidence_ai"
    elif final_ai <= HIGH_HUMAN_FINAL and both_low_ai:
        result = "high_confidence_human"
    else:
        result = "uncertain"

    confidence = max(final_ai, final_human)

    return {
        "result": result,
        "finalAiScore": round(final_ai, 2),
        "finalHumanScore": round(final_human, 2),
        "confidence": round(confidence, 2),
    }