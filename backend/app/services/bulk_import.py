"""CSV parsing shared by the bulk-invite (users) and bulk-import (contacts) flows."""

from __future__ import annotations

import csv
import io

MAX_ROWS = 500


class BulkRowError(Exception):
    """Raised for a problem with the file as a whole, not a single row."""


def parse_csv(raw: bytes, required: list[str]) -> list[dict[str, str]]:
    """Decode and parse a CSV upload into lowercase-keyed, stripped row dicts.

    Only the file-level shape is checked here (encoding, header row, required
    columns, row count) — per-row validation belongs to the caller, since
    "email is malformed" and "the file has no header" need different
    responses (one row skipped vs. the whole upload rejected).
    """
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BulkRowError(
            "The file is not valid UTF-8 text. Save it as CSV UTF-8 and try again."
        ) from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise BulkRowError("The file has no header row.")

    headers = {(h or "").strip().lower() for h in reader.fieldnames}
    missing = [column for column in required if column not in headers]
    if missing:
        raise BulkRowError(f"Missing required column(s): {', '.join(missing)}.")

    rows: list[dict[str, str]] = []
    for row in reader:
        if len(rows) >= MAX_ROWS:
            raise BulkRowError(f"A single upload cannot have more than {MAX_ROWS} rows.")
        rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in row.items()})
    return rows
