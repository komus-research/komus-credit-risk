"""Focused MP-B configuration resolution and configurable-factory tests."""

from __future__ import annotations

import unittest
from dataclasses import replace

from komus_risk.model_platform import (
    ModelConfigurationError,
    ModelConfigurationService,
    build_builtin_model_plugin_registry,
)
from komus_risk.models.gbdt import (
    CATBOOST_PROFILE,
    GBDT_MEAN_PROFILE,
    LIGHTGBM_PROFILE,
    XGBOOST_PROFILE,
    CatBoostFactory,
)


class ModelConfigurationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_builtin_model_plugin_registry()
        self.service = ModelConfigurationService(self.registry)

    def test_recommended_is_the_exact_accepted_profile_for_every_builtin(self) -> None:
        expected = {
            "catboost": CATBOOST_PROFILE,
            "xgboost": XGBOOST_PROFILE,
            "lightgbm": LIGHTGBM_PROFILE,
            "gbdt_mean": GBDT_MEAN_PROFILE,
        }
        for model_id, profile in expected.items():
            with self.subTest(model_id=model_id):
                resolved = self.service.resolve(model_id=model_id, mode="RECOMMENDED")
                self.assertEqual(resolved.resolved_parameters_dict(), profile)
                self.assertEqual(dict(resolved.user_overrides), {})

    def test_recommended_rejects_any_override(self) -> None:
        self._reject(
            "LOCKED_PARAMETER",
            model_id="catboost",
            mode="RECOMMENDED",
            user_overrides={"/estimator_params/depth": 8},
        )

    def test_advanced_sparse_values_merge_with_recommended_defaults(self) -> None:
        resolved = self.service.resolve(
            model_id="xgboost",
            mode="ADVANCED",
            user_overrides={
                "/estimator_params/learning_rate": 0.04,
                "/estimator_params/max_depth": 5,
            },
        )
        profile = resolved.resolved_parameters_dict()
        self.assertEqual(profile["estimator_params"]["learning_rate"], 0.04)
        self.assertEqual(profile["estimator_params"]["max_depth"], 5)
        self.assertEqual(profile["estimator_params"]["reg_lambda"], 1.0)
        self.assertEqual(profile["fit_recipe"], XGBOOST_PROFILE["fit_recipe"])

    def test_each_standalone_model_accepts_its_declared_advanced_value(self) -> None:
        cases = (
            ("catboost", "/estimator_params/depth", 8),
            ("xgboost", "/estimator_params/min_child_weight", 4.0),
            ("lightgbm", "/estimator_params/num_leaves", 63),
        )
        for model_id, path, value in cases:
            with self.subTest(model_id=model_id):
                resolved = self.service.resolve(
                    model_id=model_id, mode="ADVANCED", user_overrides={path: value}
                )
                self.assertEqual(
                    resolved.resolved_parameters_dict()["estimator_params"][
                        path.rsplit("/", 1)[1]
                    ],
                    value,
                )

    def test_fail_closed_error_codes(self) -> None:
        cases = (
            ("UNKNOWN_MODEL", "missing", "ADVANCED", {}),
            (
                "UNKNOWN_PARAMETER",
                "catboost",
                "ADVANCED",
                {"/estimator_params/unknown": 1},
            ),
            ("INVALID_NESTED_PATH", "catboost", "ADVANCED", {"/missing/depth": 1}),
            (
                "LOCKED_PARAMETER",
                "gbdt_mean",
                "ADVANCED",
                {"/aggregation/method": "other"},
            ),
            ("WRONG_TYPE", "catboost", "ADVANCED", {"/estimator_params/depth": "8"}),
            (
                "NULL_NOT_ALLOWED",
                "catboost",
                "ADVANCED",
                {"/estimator_params/depth": None},
            ),
            ("VALUE_BELOW_MIN", "catboost", "ADVANCED", {"/estimator_params/depth": 0}),
            (
                "VALUE_ABOVE_MAX",
                "catboost",
                "ADVANCED",
                {"/estimator_params/depth": 17},
            ),
        )
        for code, model_id, mode, overrides in cases:
            with self.subTest(code=code):
                self._reject(
                    code, model_id=model_id, mode=mode, user_overrides=overrides
                )

    def test_enum_and_trusted_validator_fail_closed(self) -> None:
        plugin = self.registry.get("gbdt_mean")
        aggregation = next(
            parameter
            for parameter in plugin.parameter_schema.parameters
            if parameter.parameter_path == "/aggregation/method"
        )
        editable_enum = replace(
            aggregation, editable=True, choices=(aggregation.recommended_value, "other")
        )
        schema = replace(
            plugin.parameter_schema,
            parameters=tuple(
                editable_enum if item is aggregation else item
                for item in plugin.parameter_schema.parameters
            ),
        )
        registry = type(self.registry)()
        registry.register(
            replace(
                plugin,
                parameter_schema=schema,
                validator_id="always-fail-v1",
                configuration_validator=lambda _: (_ for _ in ()).throw(ValueError()),
            )
        )
        service = ModelConfigurationService(registry)
        with self.assertRaises(ModelConfigurationError) as invalid_enum:
            service.resolve(
                model_id="gbdt_mean",
                mode="ADVANCED",
                user_overrides={"/aggregation/method": "invalid"},
            )
        self.assertEqual(invalid_enum.exception.code, "INVALID_ENUM")
        with self.assertRaises(ModelConfigurationError) as conflict:
            service.resolve(
                model_id="gbdt_mean",
                mode="ADVANCED",
                user_overrides={"/aggregation/method": "other"},
            )
        self.assertEqual(conflict.exception.code, "CROSS_PARAMETER_CONFLICT")

    def test_behavioral_identity_is_deterministic_and_ignores_override_order(
        self,
    ) -> None:
        first = self.service.resolve(
            model_id="xgboost",
            mode="ADVANCED",
            user_overrides={
                "/estimator_params/learning_rate": 0.04,
                "/estimator_params/max_depth": 5,
            },
        )
        second = self.service.resolve(
            model_id="xgboost",
            mode="ADVANCED",
            user_overrides={
                "/estimator_params/max_depth": 5,
                "/estimator_params/learning_rate": 0.04,
            },
        )
        changed = self.service.resolve(
            model_id="xgboost",
            mode="ADVANCED",
            user_overrides={"/estimator_params/learning_rate": 0.05},
        )
        self.assertEqual(
            first.resolved_configuration_hash, second.resolved_configuration_hash
        )
        self.assertNotEqual(
            first.resolved_configuration_hash, changed.resolved_configuration_hash
        )

    def test_mean_component_override_isolated_and_factory_accepts_it(self) -> None:
        resolved = self.service.resolve(
            model_id="gbdt_mean",
            mode="ADVANCED",
            user_overrides={"/components/catboost/profile/estimator_params/depth": 8},
        )
        profile = resolved.resolved_parameters_dict()
        self.assertEqual(
            profile["components"]["catboost"]["profile"]["estimator_params"]["depth"], 8
        )
        self.assertEqual(profile["components"]["xgboost"]["profile"], XGBOOST_PROFILE)
        adapter = self.registry.get("gbdt_mean").factory.create(profile, 42)
        self.assertEqual(
            adapter._component_adapters["catboost"].profile["estimator_params"][
                "depth"
            ],
            8,
        )

    def test_factory_rejects_locked_profile_mutation(self) -> None:
        profile = self.service.resolve(
            model_id="catboost",
            mode="ADVANCED",
            user_overrides={"/estimator_params/depth": 8},
        ).resolved_parameters_dict()
        profile["runtime_policy"]["device"] = "gpu"
        with self.assertRaises(ValueError):
            CatBoostFactory().create(profile, 42)

    def _reject(self, code: str, **kwargs) -> None:
        with self.assertRaises(ModelConfigurationError) as caught:
            self.service.resolve(**kwargs)
        self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
