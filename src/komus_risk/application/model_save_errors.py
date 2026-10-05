"""Stable application errors for the native model-save boundary."""

from __future__ import annotations


class ModelSaveError(ValueError):
    code = "MODEL_SAVE_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class ModelSaveContextNotReady(ModelSaveError):
    code = "MODEL_SAVE_CONTEXT_NOT_READY"


class ModelSaveSourceUnavailable(ModelSaveError):
    code = "MODEL_SAVE_SOURCE_UNAVAILABLE"


class ModelSaveSourceChanged(ModelSaveError):
    code = "MODEL_SAVE_SOURCE_CHANGED"


class ModelSaveBindingConflict(ModelSaveError):
    code = "MODEL_SAVE_BINDING_CONFLICT"


class ModelSaveIncompatible(ModelSaveError):
    code = "MODEL_SAVE_INCOMPATIBLE"
