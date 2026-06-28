"""Audit log for Provenance Guard.

Every submission writes one structured JSON entry. Entries are stored as
JSON Lines (one JSON object per line) in ``data/audit_log.jsonl`` — appends
are cheap and the file is easy to read back or inspect by hand.

M3 entry shape: timestamp, content_id, creator_id, attribution, confidence,
llm_score, status. Milestone 4 extends each entry with the stylometric signal
and the combined scoring breakdown.
"""

import json
import os
from datetime import datetime, timezone

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LOG_PATH = os.path.join(LOG_DIR, "audit_log.jsonl")


def utc_timestamp():
    """ISO 8601 UTC timestamp with millisecond precision and a trailing 'Z'."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def write_entry(entry):
    """Append one structured entry to the audit log.

    A ``timestamp`` is added automatically if the entry does not already have
    one. Returns the entry exactly as written.
    """
    if "timestamp" not in entry:
        entry = {**entry, "timestamp": utc_timestamp()}
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def get_log(limit=50):
    """Return the most recent audit entries, newest first.

    Args:
        limit: Maximum number of entries to return.
    """
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]
    entries.reverse()  # newest first
    return entries[:limit]