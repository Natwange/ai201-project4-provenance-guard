"""Signal 2: stylometric heuristics.

Uses measurable writing statistics instead of model judgment. AI-generated and
formal text tends toward denser, more sophisticated word choice; casual human
writing tends toward shorter words, contractions, and uneven rhythm.

Metrics computed (all reported; see scoring note below for which drive the
score):
    * averageWordLength       - mean characters per word (lexical density)
    * sentenceLengthVariance  - spread of words-per-sentence
    * typeTokenRatio          - vocabulary diversity (unique / total words)
    * punctuationDensity      - punctuation chars / total chars
    * averageSentenceLength   - mean words per sentence

Scoring note — calibration finding (see README): the spec's intuition that
"uniform sentences == AI" does NOT hold on real samples. A formal *human*
paragraph (e.g. academic economics) is often MORE uniform and has LONGER
sentences than actual AI text, so sentence-uniformity and sentence-length
falsely flag it as AI. Type-token ratio is ~0.87 for every short sample, so it
carries no signal at these lengths. The one metric that orders samples
sensibly is average word length, so it drives ~80% of the score; sentence
length and uniformity contribute lightly. This signal therefore CANNOT
reliably separate AI from polished formal human writing — that is the
documented blind spot, and the combined scoring relies on the LLM signal plus
the false-positive-avoiding thresholds to handle it.

Returns:
    {
        "signal": "stylometric",
        "aiScore": 0.71,
        "humanScore": 0.29,
        "metrics": { ... }
    }
"""

import re
import statistics

# Calibration constants, tuned against the M4 test inputs (see README). Round
# numbers chosen deliberately; widen these as more samples are gathered.
_AWL_HUMAN = 4.3     # avg word length (chars) at/below which reads casual-human
_AWL_AI = 6.8        # avg word length at/above which reads dense/formal
_ASL_HUMAN = 11.0    # avg sentence length (words) at/below which reads human
_ASL_AI = 23.0       # avg sentence length at/above which reads AI/formal
_CV_HUMAN = 0.55     # coefficient of variation at/above which reads human
_CV_AI = 0.28        # coefficient of variation at/below which reads uniform/AI

# Weights for the three scoring sub-signals (must sum to 1.0). Average word
# length dominates; the other two are weak and partly misleading (see note).
_W_WORDLEN = 0.8
_W_LEN = 0.1
_W_UNIFORM = 0.1


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _words(text):
    """Word tokens (letters and apostrophes), used for counts, awl, and TTR."""
    return re.findall(r"[A-Za-z']+", text)


def _split_sentences(text):
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def analyze_stylometric_signal(text):
    """Run the stylometric signal over ``text`` and return a signal dict."""
    words = _words(text)
    total_words = len(words)
    sentences = _split_sentences(text)

    sentence_lengths = [len(_words(s)) for s in sentences] or [total_words]

    avg_word_length = statistics.fmean(len(w) for w in words) if words else 0.0
    avg_sentence_length = statistics.fmean(sentence_lengths) if sentence_lengths else 0.0
    variance = statistics.pvariance(sentence_lengths) if len(sentence_lengths) > 1 else 0.0
    cv = (variance ** 0.5 / avg_sentence_length) if avg_sentence_length else 0.0

    ttr = (len({w.lower() for w in words}) / total_words) if total_words else 0.0

    punct_count = len(re.findall(r"""[,.;:!?"'()\-]""", text))
    punctuation_density = punct_count / max(len(text), 1)

    # --- Sub-scores: each is "AI-ness" in [0, 1] ---
    # Dense, long words read AI/formal. (Primary, length-robust discriminator.)
    ai_wordlen = _clamp((avg_word_length - _AWL_HUMAN) / (_AWL_AI - _AWL_HUMAN))
    # Long average sentences lean AI/formal. (Weak; flags formal humans too.)
    ai_len = _clamp((avg_sentence_length - _ASL_HUMAN) / (_ASL_AI - _ASL_HUMAN))
    # Uniform sentence rhythm leans AI. (Weak; flags formal humans too.)
    ai_uniform = _clamp((_CV_HUMAN - cv) / (_CV_HUMAN - _CV_AI))

    ai_score = _clamp(_W_WORDLEN * ai_wordlen + _W_LEN * ai_len + _W_UNIFORM * ai_uniform)
    ai_score = round(ai_score, 2)

    return {
        "signal": "stylometric",
        "aiScore": ai_score,
        "humanScore": round(1 - ai_score, 2),
        "metrics": {
            "averageWordLength": round(avg_word_length, 2),
            "sentenceLengthVariance": round(variance, 2),
            "typeTokenRatio": round(ttr, 2),
            "punctuationDensity": round(punctuation_density, 3),
            "averageSentenceLength": round(avg_sentence_length, 1),
        },
    }