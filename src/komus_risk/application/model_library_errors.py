"""Stable errors for trusted saved-model library reads."""

from __future__ import annotations


class ModelLibraryError(ValueError):
    code = "MODEL_LIBRARY_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class InvalidModelLibraryQuery(ModelLibraryError):
    code = "INVALID_MODEL_LIBRARY_QUERY"


class InvalidModelDisplayName(ModelLibraryError):
    code = "INVALID_MODEL_DISPLAY_NAME"


class ModelVersionNotFound(ModelLibraryError):
    code = "MODEL_VERSION_NOT_FOUND"


class ModelVersionIntegrityError(ModelLibraryError):
    code = "MODEL_VERSION_INTEGRITY_ERROR"


class ModelSourceResultUnavailable(ModelLibraryError):
    code = "MODEL_SOURCE_RESULT_UNAVAILABLE"
