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


def _read_all():
    """Return all entries in file order (oldest first); [] if none."""
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def get_log(limit=50):
    """Return the most recent audit entries, newest first.

    Args:
        limit: Maximum number of entries to return.
    """
    entries = _read_all()
    entries.reverse()  # newest first
    return entries[:limit]


def find_submission(content_id):
    """Return the most recent submission (classification) entry for a content_id.

    Appeal entries are skipped. Returns None if no submission is found.
    """
    for entry in reversed(_read_all()):
        if entry.get("content_id") == content_id and entry.get("event") != "appeal":
            return entry
    return None


def set_status(content_id, status, extra=None):
    """Update submission entries for a content_id in place.

    Rewrites the log file, setting ``status`` (and merging any ``extra`` fields)
    on every submission entry matching ``content_id``. Returns the number of
    entries updated.
    """
    entries = _read_all()
    updated = 0
    for entry in entries:
        if entry.get("content_id") == content_id and entry.get("event") != "appeal":
            entry["status"] = status
            if extra:
                entry.update(extra)
            updated += 1
    if updated:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
    return updated
