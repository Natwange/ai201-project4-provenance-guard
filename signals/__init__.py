"""Detection signals for Provenance Guard."""

from .llm_signal import analyze_llm_signal
from .stylometric_signal import analyze_stylometric_signal

__all__ = ["analyze_llm_signal", "analyze_stylometric_signal"]