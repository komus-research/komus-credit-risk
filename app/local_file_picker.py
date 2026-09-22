"""Safe persistence for files selected through the Streamlit uploader."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


class UnsupportedLocalFileExtension(ValueError):
    """Raised when the selected local file has a disallowed extension."""


def persist_uploaded_file(
    file_name: str,
    content: bytes,
    supported_extensions: tuple[str, ...],
    *,
    upload_root: Path | None = None,
) -> str:
    """Persist an uploaded file under an ignored runtime directory."""
    extensions = tuple(sorted({extension.lower() for extension in supported_extensions}))
    safe_name = Path(file_name).name
    suffix = Path(safe_name).suffix.lower()
    if not safe_name or suffix not in extensions:
        supported = ", ".join(extensions)
        raise UnsupportedLocalFileExtension(
            f"Неподдерживаемое расширение файла. Разрешены только: {supported}."
        )
    if not isinstance(content, bytes):
        raise TypeError("Содержимое загруженного файла должно быть передано как bytes.")

    root = upload_root or Path(__file__).resolve().parents[1] / ".streamlit-artifacts" / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    content_hash = sha256(content).hexdigest()
    target = root / f"{content_hash[:16]}-{safe_name}"
    if not target.exists():
        target.write_bytes(content)
    return str(target.resolve())
