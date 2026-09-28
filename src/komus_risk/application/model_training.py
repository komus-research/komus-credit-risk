"""Final fit from an immutable successful OOF experiment artifact."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

import numpy as np

from komus_risk.artifacts import ExperimentArtifactStore
from komus_risk.artifacts.model_store import ModelVersionStore, ModelVersionSummary
from komus_risk.contracts import FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.hashing import stable_hash
from komus_risk.model_platform import ModelPluginRegistry
from komus_risk.models import ModelAdapterFactory
from komus_risk.registries import FeatureRegistry, ModelRegistry


class FinalModelTrainingService:
    """Fits exactly the evaluated configuration on its approved population."""

    def __init__(
        self,
        *,
        experiment_artifact_store: ExperimentArtifactStore,
        model_version_store: ModelVersionStore,
        model_registry: ModelRegistry,
        model_factories: Mapping[str, ModelAdapterFactory],
        code_version: str,
        model_plugin_registry: ModelPluginRegistry | None = None,
    ) -> None:
        if not isinstance(code_version, str) or not code_version.strip():
            raise ValueError("code_version must be a non-empty string.")
        self.experiment_artifact_store = experiment_artifact_store
        self.model_version_store = model_version_store
        self.model_registry = model_registry
        self.model_factories = dict(model_factories)
        self.code_version = code_version
        self.model_plugin_registry = model_plugin_registry
        if self.model_version_store.code_version != code_version:
            raise ValueError(
                "ModelVersionStore must use the service trusted code_version."
            )

    def train(
        self,
        *,
        experiment_artifact_id: str,
        loaded_dataset: LoadedDataset,
        feature_registry: FeatureRegistry,
        population: EvaluationPopulation,
    ) -> ModelVersionSummary:
        artifact = self.experiment_artifact_store.load(experiment_artifact_id)
        contract, config = loaded_dataset.contract, artifact.config
        self._validate_source(loaded_dataset)
        if (
            artifact.dataset_contract != contract
            or config.dataset_id != contract.dataset_id
            or config.dataset_fingerprint != contract.dataset_fingerprint
        ):
            raise ValueError(
                "Current dataset does not exactly match the experiment artifact."
            )
        expected_role = "working" if contract.final_test_locked else "full"
        if population.partition_role != expected_role:
            raise ValueError(f"Final fit requires the {expected_role} population.")
        if artifact.population != population:
            raise ValueError(
                "Current population does not exactly match the experiment artifact."
            )
        if (
            contract.feature_registry_id != feature_registry.registry_id
            or contract.feature_registry_hash != feature_registry.registry_hash
        ):
            raise ValueError(
                "Current FeatureRegistry is not bound to the current dataset."
            )
        if artifact.run_output.result.code_version != self.code_version:
            raise ValueError(
                "Experiment artifact code identity is incompatible with final fit."
            )
        specs = feature_registry.resolve(config.feature_ids)
        if any(
            spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED for spec in specs
        ):
            raise ValueError(
                "Experiment feature set is not model-eligible in the current registry."
            )
        columns = [spec.column_name for spec in specs]
        if any(column not in loaded_dataset.dataframe.columns for column in columns):
            raise ValueError(
                "Experiment predictor columns are absent from the current dataset."
            )
        configuration_record = artifact.configuration_record
        if configuration_record is None:
            spec = self.model_registry.get(config.model_id)
            factory = self.model_factories.get(config.model_id)
            if (
                factory is None
                or (factory.model_id, factory.model_version, factory.adapter_version)
                != (spec.model_id, spec.version, spec.adapter_version)
                or spec.version != config.model_version
                or config.model_parameters != spec.default_profile
            ):
                raise ValueError(
                    "Experiment model recipe is incompatible with the current registry/factory."
                )
        else:
            if self.model_plugin_registry is None:
                raise ValueError(
                    "Trusted model plugin registry is required for MP-C final fit."
                )
            try:
                plugin = self.model_plugin_registry.get(config.model_id)
            except (KeyError, ValueError) as error:
                raise ValueError(
                    "Experiment model plugin is not trusted at final fit."
                ) from error
            if (
                configuration_record.model_id,
                configuration_record.model_version,
                configuration_record.adapter_version,
                configuration_record.plugin_contract_hash,
            ) != (
                plugin.spec.model_id,
                plugin.spec.version,
                plugin.spec.adapter_version,
                plugin.plugin_contract_hash,
            ):
                raise ValueError(
                    "Experiment configuration provenance is incompatible with current plugin."
                )
            if configuration_record.resolved_parameters != config.model_parameters:
                raise ValueError(
                    "Experiment configuration provenance parameters do not match experiment."
                )
            if (
                configuration_record.schema_id,
                configuration_record.schema_version,
                configuration_record.schema_hash,
                configuration_record.recommended_profile_id,
                configuration_record.recommended_profile_hash,
            ) != (
                plugin.parameter_schema.schema_id,
                plugin.parameter_schema.schema_version,
                plugin.parameter_schema.schema_hash,
                plugin.recommended_profile.profile_id,
                plugin.recommended_profile.profile_hash,
            ):
                raise ValueError(
                    "Experiment configuration provenance schema/profile is incompatible with current plugin."
                )
            expected_resolved_hash = stable_hash(
                {
                    "model_id": plugin.spec.model_id,
                    "model_version": plugin.spec.version,
                    "adapter_version": plugin.spec.adapter_version,
                    "schema_hash": plugin.parameter_schema.schema_hash,
                    "resolved_parameters": dict(config.model_parameters),
                }
            )
            if (
                configuration_record.resolved_configuration_hash
                != expected_resolved_hash
            ):
                raise ValueError(
                    "Experiment configuration provenance resolved hash is invalid."
                )
            if (config.model_id, config.model_version) != (
                plugin.spec.model_id,
                plugin.spec.version,
            ):
                raise ValueError(
                    "Experiment configuration is incompatible with current plugin."
                )
            factory = plugin.factory
        frame = loaded_dataset.dataframe.iloc[list(population.row_positions)]
        target = frame[contract.target_column]
        if (
            target.isna().any()
            or target.nunique(dropna=False) != 2
            or not target.eq(contract.positive_class).any()
        ):
            raise ValueError("Final-fit population has an invalid binary target.")
        adapter = factory.create(dict(config.model_parameters), config.seed)
        adapter.fit(
            frame.loc[:, columns], target.eq(contract.positive_class).astype(int)
        )
        probabilities = np.asarray(
            adapter.predict_positive_proba(frame.loc[:, columns]), dtype=float
        )
        if (
            probabilities.ndim != 1
            or len(probabilities) != len(frame)
            or not np.isfinite(probabilities).all()
            or (probabilities < 0).any()
            or (probabilities > 1).any()
        ):
            raise ValueError(
                "Fitted adapter did not return valid positive probabilities."
            )
        return self.model_version_store.save(
            experiment_artifact_id=experiment_artifact_id,
            dataset_contract=contract,
            config=config,
            feature_specs=specs,
            feature_registry=feature_registry,
            population=population,
            adapter=adapter,
            source_file_sha256=loaded_dataset.source_file_sha256,
            configuration_record=configuration_record,
        )

    @staticmethod
    def _validate_source(loaded_dataset: LoadedDataset) -> None:
        path = Path(loaded_dataset.source_path)
        if not path.is_file():
            raise ValueError(
                "Original dataset source file is unavailable; final fit is forbidden."
            )
        digest = sha256(path.read_bytes()).hexdigest()
        if digest != loaded_dataset.source_file_sha256:
            raise ValueError(
                "Original dataset source file changed after evaluation; final fit is forbidden."
            )
