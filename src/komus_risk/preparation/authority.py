"""Backend-owned authority for Dataset Preparation contexts."""

from __future__ import annotations

from komus_risk.hashing import stable_hash

from .context import PreparedDatasetContext


class PreparedDatasetContextAuthorityError(ValueError):
    """Stable error raised when trusted prepared-context authority fails."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def prepared_context_semantic_hash(context: PreparedDatasetContext) -> str:
    """Hash all facts an accepted context is allowed to establish."""
    return stable_hash(
        {
            "display_name": context.display_name,
            "dataset_contract": context.loaded_dataset.contract.to_dict(),
            "feature_registry_id": context.feature_registry.registry_id,
            "feature_registry_hash": context.feature_registry.registry_hash,
            "population_id": context.population.population_id,
            "population_fingerprint": context.population.population_fingerprint,
            "partition_role": context.population.partition_role,
            "row_positions": list(context.population.row_positions),
        }
    )


class PreparedDatasetContextAuthority:
    """In-memory backend registry of contexts accepted by preparation services.

    This deliberately stores the original object: a reference supplied by a
    caller is never itself authoritative, even when it reuses a known id.
    """

    def __init__(self) -> None:
        self._contexts: dict[str, PreparedDatasetContext] = {}
        self._semantic_hashes: dict[str, str] = {}

    def register(self, context: PreparedDatasetContext) -> PreparedDatasetContext:
        if not isinstance(context, PreparedDatasetContext):
            raise TypeError("context must be PreparedDatasetContext.")
        context_id = context.context_id
        if not isinstance(context_id, str) or not context_id.strip():
            raise PreparedDatasetContextAuthorityError("INVALID_CONTEXT_REFERENCE")
        semantic_hash = prepared_context_semantic_hash(context)
        existing = self._contexts.get(context_id)
        if existing is None:
            self._contexts[context_id] = context
            self._semantic_hashes[context_id] = semantic_hash
            return context
        if self._semantic_hashes[context_id] != semantic_hash:
            raise PreparedDatasetContextAuthorityError(
                "CONFLICTING_CONTEXT_REGISTRATION"
            )
        return existing

    def resolve(self, context_id: str) -> PreparedDatasetContext:
        if not isinstance(context_id, str) or not context_id.strip():
            raise PreparedDatasetContextAuthorityError("INVALID_CONTEXT_REFERENCE")
        try:
            return self._contexts[context_id]
        except KeyError as error:
            raise PreparedDatasetContextAuthorityError(
                "TRUSTED_CONTEXT_NOT_FOUND"
            ) from error
