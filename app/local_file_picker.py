"""UI-only native local file picker for the Streamlit prototype."""

from __future__ import annotations

from collections.abc import Iterable


class NativeFilePickerUnavailable(RuntimeError):
    """Raised when a native dialog cannot be opened in this runtime."""


def choose_local_file(supported_extensions: Iterable[str]) -> str | None:
    """Return a path selected on the Streamlit host machine, without uploading it.

    Tk is imported lazily so a headless or non-Windows deployment can still use
    the manual-path fallback without importing platform UI dependencies.
    """
    extensions = tuple(sorted({extension.lower() for extension in supported_extensions}))
    file_types = [("Поддерживаемые файлы", " ".join(f"*{extension}" for extension in extensions)), ("Все файлы", "*.*")]
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askopenfilename(title="Выберите файл данных", filetypes=file_types)
        finally:
            root.destroy()
    except Exception as error:  # The UI must fall back cleanly on headless hosts.
        raise NativeFilePickerUnavailable from error
    return selected or None
