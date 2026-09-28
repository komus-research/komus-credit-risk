"""Trusted, declarative Russian presentation metadata for model catalogs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from komus_risk.hashing import stable_hash

from .contracts import ModelPlugin
from .registry import ModelPluginRegistry


class ModelPresentationError(ValueError):
    """Stable failure for an invalid trusted catalog presentation composition."""

    def __init__(self) -> None:
        self.code = "INVALID_MODEL_PRESENTATION_COMPOSITION"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ModelParameterPresentation:
    parameter_path: str
    display_name_ru: str
    description_ru: str

    def __post_init__(self) -> None:
        if not isinstance(
            self.parameter_path, str
        ) or not self.parameter_path.startswith("/"):
            raise ModelPresentationError()
        if any(
            not isinstance(text, str) or not text.strip()
            for text in (self.display_name_ru, self.description_ru)
        ):
            raise ModelPresentationError()

    def to_dict(self) -> dict[str, str]:
        return {
            "parameter_path": self.parameter_path,
            "display_name_ru": self.display_name_ru,
            "description_ru": self.description_ru,
        }


@dataclass(frozen=True, slots=True)
class ModelPresentationProfile:
    presentation_schema_version: str
    presentation_profile_id: str
    presentation_profile_version: str
    locale: str
    model_id: str
    model_version: str
    adapter_version: str
    schema_id: str
    schema_version: str
    schema_hash: str
    parameters: tuple[ModelParameterPresentation, ...]
    presentation_hash: str = ""

    def __post_init__(self) -> None:
        fields = (
            self.presentation_schema_version,
            self.presentation_profile_id,
            self.presentation_profile_version,
            self.model_id,
            self.model_version,
            self.adapter_version,
            self.schema_id,
            self.schema_version,
            self.schema_hash,
        )
        if (
            any(not isinstance(value, str) or not value.strip() for value in fields)
            or self.locale != "ru"
        ):
            raise ModelPresentationError()
        try:
            parameters = tuple(
                item
                if isinstance(item, ModelParameterPresentation)
                else ModelParameterPresentation(**item)
                for item in self.parameters
            )
        except (TypeError, ValueError) as error:
            raise ModelPresentationError() from error
        paths = [item.parameter_path for item in parameters]
        if len(paths) != len(set(paths)):
            raise ModelPresentationError()
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(
            self, "presentation_hash", stable_hash(self.canonical_payload())
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "presentation_schema_version": self.presentation_schema_version,
            "presentation_profile_id": self.presentation_profile_id,
            "presentation_profile_version": self.presentation_profile_version,
            "locale": self.locale,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "adapter_version": self.adapter_version,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "schema_hash": self.schema_hash,
            "parameters": [
                entry.to_dict()
                for entry in sorted(
                    self.parameters, key=lambda item: item.parameter_path
                )
            ],
        }


class ModelPresentationRegistry:
    """Immutable-profile registrations from trusted backend composition code."""

    def __init__(self, profiles: Sequence[ModelPresentationProfile] = ()) -> None:
        self._profiles: list[ModelPresentationProfile] = []
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ModelPresentationProfile) -> ModelPresentationProfile:
        if not isinstance(profile, ModelPresentationProfile):
            raise ModelPresentationError()
        self._profiles.append(profile)
        return profile

    def list(self) -> tuple[ModelPresentationProfile, ...]:
        return tuple(self._profiles)


@dataclass(frozen=True, slots=True)
class ModelCatalogComposition:
    """Validated all-or-nothing presentation binding for one plugin registry."""

    _by_model: Mapping[str, Mapping[str, ModelParameterPresentation]]

    def __post_init__(self) -> None:
        frozen = {
            model_id: MappingProxyType(dict(values))
            for model_id, values in self._by_model.items()
        }
        object.__setattr__(self, "_by_model", MappingProxyType(frozen))

    @classmethod
    def compose(
        cls,
        plugins: ModelPluginRegistry | Sequence[ModelPlugin],
        presentations: ModelPresentationRegistry,
    ) -> ModelCatalogComposition:
        try:
            plugin_snapshot = (
                tuple(plugins.list())
                if isinstance(plugins, ModelPluginRegistry)
                else tuple(plugins)
            )
            if any(not isinstance(plugin, ModelPlugin) for plugin in plugin_snapshot):
                raise ValueError
            plugin_by_id = {plugin.spec.model_id: plugin for plugin in plugin_snapshot}
            profiles = presentations.list()
            bound: dict[str, ModelPresentationProfile] = {}
            for profile in profiles:
                plugin = plugin_by_id.get(profile.model_id)
                if plugin is None:
                    raise ValueError
                schema = plugin.parameter_schema
                spec = plugin.spec
                if (
                    profile.model_version,
                    profile.adapter_version,
                    profile.schema_id,
                    profile.schema_version,
                    profile.schema_hash,
                ) != (
                    spec.version,
                    spec.adapter_version,
                    schema.schema_id,
                    schema.schema_version,
                    schema.schema_hash,
                ):
                    raise ValueError
                if profile.model_id in bound:
                    raise ValueError
                expected = {item.parameter_path for item in schema.parameters}
                actual = [item.parameter_path for item in profile.parameters]
                if len(actual) != len(set(actual)) or set(actual) != expected:
                    raise ValueError
                bound[profile.model_id] = profile
            if set(bound) != set(plugin_by_id):
                raise ValueError
            values = {
                model_id: MappingProxyType(
                    {item.parameter_path: item for item in profile.parameters}
                )
                for model_id, profile in bound.items()
            }
            return cls(MappingProxyType(values))
        except Exception as error:
            if isinstance(error, ModelPresentationError):
                raise
            raise ModelPresentationError() from error

    def parameter(
        self, model_id: str, parameter_path: str
    ) -> ModelParameterPresentation:
        return self._by_model[model_id][parameter_path]


_COPY: dict[str, tuple[str, str]] = {
    "iterations": ("Итерации", "Количество итераций обучения модели."),
    "learning_rate": ("Скорость обучения", "Шаг обновления модели на каждой итерации."),
    "depth": ("Глубина дерева", "Максимальная глубина дерева в модели."),
    "n_estimators": ("Количество деревьев", "Количество деревьев в ансамбле."),
    "max_depth": (
        "Максимальная глубина дерева",
        "Максимальная глубина дерева в модели.",
    ),
    "min_child_weight": (
        "Минимальный вес дочернего узла",
        "Минимальная сумма весов объектов для дочернего узла.",
    ),
    "subsample": (
        "Доля объектов для обучения",
        "Доля объектов, используемая при построении дерева.",
    ),
    "colsample_bytree": (
        "Доля признаков для дерева",
        "Доля признаков, используемая при построении дерева.",
    ),
    "reg_alpha": ("L1-регуляризация", "Коэффициент L1-регуляризации весов модели."),
    "reg_lambda": ("L2-регуляризация", "Коэффициент L2-регуляризации весов модели."),
    "num_leaves": ("Количество листьев", "Максимальное количество листьев дерева."),
    "min_child_samples": (
        "Минимум объектов в листе",
        "Минимальное количество объектов в листе дерева.",
    ),
    "subsample_freq": ("Частота подвыборки", "Частота обновления подвыборки объектов."),
    "method": ("Метод агрегации", "Способ объединения вероятностей компонентов."),
    "model_version": ("Версия модели", "Зафиксированная версия компонента ансамбля."),
    "adapter_version": (
        "Версия адаптера",
        "Зафиксированная версия адаптера компонента.",
    ),
}
_COMPONENT = {"catboost": "CatBoost", "xgboost": "XGBoost", "lightgbm": "LightGBM"}
_BUILTIN_MODEL_IDS = frozenset({"catboost", "xgboost", "lightgbm", "gbdt_mean"})


def builtin_model_presentation_registry(
    plugins: ModelPluginRegistry,
) -> ModelPresentationRegistry:
    """Create trusted V1 Russian profiles for the current built-in plugins."""
    profiles = []
    for plugin in plugins.list():
        if plugin.spec.model_id not in _BUILTIN_MODEL_IDS:
            continue
        spec, schema = plugin.spec, plugin.parameter_schema
        entries = []
        for parameter in schema.parameters:
            path = parameter.parameter_path
            leaf = path.rsplit("/", 1)[-1]
            try:
                name, description = _COPY[leaf]
            except KeyError as error:
                raise ModelPresentationError() from error
            if path.startswith("/components/"):
                component = path.split("/", 3)[2]
                context = _COMPONENT[component]
                name = f"{context} — {name}"
                description = f"{context}: {description}"
            entries.append(ModelParameterPresentation(path, name, description))
        profiles.append(
            ModelPresentationProfile(
                "1",
                f"{spec.model_id}_ru",
                "1",
                "ru",
                spec.model_id,
                spec.version,
                spec.adapter_version,
                schema.schema_id,
                schema.schema_version,
                schema.schema_hash,
                tuple(entries),
            )
        )
    return ModelPresentationRegistry(profiles)
