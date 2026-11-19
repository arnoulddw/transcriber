"""Human-readable text for the "transcript may be incomplete" warning."""
import json
from typing import Any, Dict, List, Optional

from flask_babel import gettext as _


def parse_transcription_warning_detail(raw: Any) -> Optional[Dict[str, Any]]:
    """Return {"empty_chunks": [...], "total_chunks": n} or None when unusable."""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None

    try:
        total = int(raw.get("total_chunks") or 0)
        empty: List[int] = sorted({int(n) for n in raw.get("empty_chunks") or []})
    except (TypeError, ValueError):
        return None
    if total <= 0 or not empty:
        return None
    return {"empty_chunks": empty, "total_chunks": total}


def describe_transcription_warning(has_warning: bool, detail: Optional[Dict[str, Any]]) -> Optional[str]:
    """Explain why a transcript may be incomplete, or None when there is no warning."""
    if not has_warning:
        return None
    if not detail:
        return _("Transcript may be incomplete")

    empty = detail["empty_chunks"]
    total = detail["total_chunks"]

    if total == 1:
        return _(
            "Transcript may be incomplete: the audio returned no text, "
            "usually because it is silent."
        )
    if len(empty) == 1:
        chunk = empty[0]
        if chunk == total:
            return _(
                "Transcript may be incomplete: the last audio chunk (%(chunk)s of %(total)s) "
                "returned no text, usually because that part is silent.",
                chunk=chunk, total=total,
            )
        return _(
            "Transcript may be incomplete: audio chunk %(chunk)s of %(total)s "
            "returned no text, usually because that part is silent.",
            chunk=chunk, total=total,
        )
    return _(
        "Transcript may be incomplete: %(num)s of %(total)s audio chunks returned no text "
        "(chunks %(chunks)s), usually because those parts are silent.",
        num=len(empty), total=total, chunks=", ".join(str(n) for n in empty),
    )
