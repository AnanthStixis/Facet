"""Tenant asset storage (logos today, exported files later)."""

from __future__ import annotations

import uuid
from pathlib import Path

from app.core.config import settings
from app.core.errors import ValidationFailed

# Raster and SVG only. SVG is accepted because logos are usually vector, but it
# is served with a restrictive content type and never inlined into a page:
# an SVG is an executable document, and a tenant-uploaded one rendered inline
# would be stored cross-site scripting against every user of that tenant.
ALLOWED_LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}

_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"RIFF": "image/webp",
}


def _sniff(data: bytes) -> str | None:
    for signature, content_type in _MAGIC.items():
        if data.startswith(signature):
            return content_type
    stripped = data.lstrip()[:200].lower()
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<svg"):
        return "image/svg+xml"
    return None


def validate_logo(data: bytes, declared_type: str) -> str:
    if len(data) > settings.logo_max_bytes:
        raise ValidationFailed(
            f"The logo must be smaller than {settings.logo_max_bytes // 1024} KB."
        )
    if declared_type not in ALLOWED_LOGO_TYPES:
        raise ValidationFailed(
            "Use a PNG, JPEG, WebP or SVG file. Recommended: 320x80 px, transparent PNG."
        )
    # Trust the bytes, not the Content-Type header the client chose to send.
    sniffed = _sniff(data)
    if sniffed is None or sniffed != declared_type:
        raise ValidationFailed("That file does not appear to be the image type it claims.")
    return declared_type


def store_logo(org_id: uuid.UUID, data: bytes, content_type: str) -> str:
    """Write the logo and return a path relative to the storage root.

    A new filename is generated on every upload rather than overwriting, so a
    CDN or browser cache cannot serve the previous logo after a rebrand.
    """
    extension = ALLOWED_LOGO_TYPES[content_type]
    relative = Path("branding") / str(org_id) / f"logo-{uuid.uuid4().hex[:12]}{extension}"
    absolute = settings.storage_path / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(data)

    # Remove superseded logos so a tenant cannot accumulate storage.
    for existing in absolute.parent.iterdir():
        if existing.is_file() and existing != absolute:
            existing.unlink(missing_ok=True)

    return relative.as_posix()


def read_logo(relative_path: str) -> tuple[bytes, str] | None:
    absolute = (settings.storage_path / relative_path).resolve()
    root = settings.storage_path.resolve()
    # Defence against a traversal value reaching this from the database.
    if root not in absolute.parents:
        return None
    if not absolute.exists():
        return None
    suffix = absolute.suffix.lower()
    content_type = next(
        (ct for ct, ext in ALLOWED_LOGO_TYPES.items() if ext == suffix),
        "application/octet-stream",
    )
    return absolute.read_bytes(), content_type

def delete_logo(relative_path: str) -> None:
    absolute = (settings.storage_path / relative_path).resolve()
    root = settings.storage_path.resolve()
    if root not in absolute.parents:
        return
    absolute.unlink(missing_ok=True)
