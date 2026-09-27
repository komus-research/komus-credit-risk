from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class _RoleTab:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _RoleSessionState(dict):
    def __getattr__(self, name: str):
        return self[name]


class _RoleUiStreamlit:
    def __init__(self, *, pressed_key: str, session_state: dict) -> None:
        self.pressed_key = pressed_key
        self.session_state = _RoleSessionState(session_state)
        self.tab_labels: list[str] = []
        self.button_keys: list[str] = []
        self.rerun_count = 0

    def subheader(self, *args, **kwargs) -> None:
        pass

    def caption(self, *args, **kwargs) -> None:
        pass

    def info(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass

    def write(self, *args, **kwargs) -> None:
        pass

    def tabs(self, labels: list[str]) -> list[_RoleTab]:
        self.tab_labels = labels
        return [_RoleTab() for _ in labels]

    def button(self, label: str, *, key: str, type: str) -> bool:
        self.button_keys.append(key)
        return key == self.pressed_key

    def rerun(self) -> None:
        self.rerun_count += 1


class _RoleUiWorkflow:
    def __init__(self) -> None:
        self.prepare_calls: list[str] = []
        self.provider_calls: list[str] = []

    def capabilities(self, *, local_explanation_evidence):
        return {"result_interpretation": SimpleNamespace(state="AVAILABLE")}

    def prepare_interpretation(self, *, evidence, loaded_model_version, recipient_role):
        self.prepare_calls.append(recipient_role)
        return SimpleNamespace(recipient_role=recipient_role)

    def interpret(self, *, request):
        self.provider_calls.append(request.recipient_role)
        return SimpleNamespace(
            response=SimpleNamespace(text=f"response for {request.recipient_role}"),
            dispatch_receipt=object(),
        )


class _StopRerun(RuntimeError):
    pass


class _InferenceUploadStatus:
    def write(self, *_args, **_kwargs) -> None:
        pass

    def update(self, **_kwargs) -> None:
        pass


class _InferenceUploadStreamlit:
    def __init__(self, *, upload, session_state: dict) -> None:
        self.upload = upload
        self.session_state = _RoleSessionState(session_state)

    def divider(self) -> None:
        pass

    def subheader(self, *_args, **_kwargs) -> None:
        pass

    def success(self, *_args, **_kwargs) -> None:
        pass

    def write(self, *_args, **_kwargs) -> None:
        pass

    def caption(self, *_args, **_kwargs) -> None:
        pass

    def code(self, *_args, **_kwargs) -> None:
        pass

    def error(self, *_args, **_kwargs) -> None:
        pass

    def expander(self, *_args, **_kwargs) -> _RoleTab:
        return _RoleTab()

    def file_uploader(self, *_args, **_kwargs):
        return self.upload

    def button(self, _label: str, **kwargs) -> bool:
        return kwargs.get("key") == "run-targetless-inference"

    def status(self, *_args, **_kwargs) -> _InferenceUploadStatus:
        return _InferenceUploadStatus()

    def rerun(self) -> None:
        raise _StopRerun


class _InferenceUploadWorkflow:
    def __init__(self) -> None:
        self.predict_calls: list[tuple[object, object]] = []

    def capabilities(self, **_kwargs):
        return {"final_model_save": SimpleNamespace(state="AVAILABLE")}

    def predict(self, *, loaded_model_version, snapshot):
        self.predict_calls.append((loaded_model_version, snapshot))
        return object()


class _Upload:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


class StreamlitIntegrationUiTests(unittest.TestCase):
    def test_result_ui_uses_facade_and_dynamic_prediction_identifier(self) -> None:
        from app import streamlit_app

        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")

        self.assertIn("workflow.save_model(", source)
        self.assertIn("workflow.predict(", source)
        self.assertIn("workflow.explain(", source)
        self.assertIn("workflow.prepare_interpretation(", source)
        self.assertIn("loaded_model_version=loaded_model_version", source)
        self.assertIn("recipient_role=recipient_role", source)
        self.assertIn("result_interpreter_requests_by_role", source)
        self.assertIn("result_interpreter_responses_by_role", source)
        self.assertIn("workflow.interpret(", source)
        self.assertIn("request-result-interpretation-{role}", source)
        self.assertNotIn("interpret-result-for-four-roles", source)
        self.assertNotIn("for role in missing_roles", source)
        self.assertIn("Менеджер по продажам", source)
        self.assertIn("Кредитный контролёр", source)
        self.assertIn("Юрист", source)
        self.assertIn("Информационная безопасность", source)
        self.assertIn(
            "Автоматическое текстовое объяснение отключено политикой передачи данных.",
            source,
        )
        self.assertIn(
            "Текстовое объяснение разрешено, но не настроено в текущем запуске.", source
        )
        self.assertIn("Повторить для роли", source)
        self.assertIn("Текст для этой роли сейчас недоступен.", source)
        self.assertIn("не являются кредитным решением", source)
        self.assertIn("prediction_batch.identifier_column", source)
        self.assertIn("st.file_uploader(", source)
        self.assertIn("stage_browser_upload(", source)
        self.assertIn("TabularReader().read(staged.local_path)", source)
        self.assertNotIn(
            "text_input", inspect.getsource(streamlit_app._render_local_model_use_flow)
        )
        self.assertIn('"Алгоритм"', source)
        self.assertIn('"Готовим модель для прогноза"', source)
        self.assertIn('"Модель готова для прогноза"', source)
        self.assertIn(
            '"Выберите файл с организациями, для которых нужно получить прогноз.',
            source,
        )
        self.assertIn('"Проверяем файл и рассчитываем прогноз"', source)
        self.assertIn('"Рассчитываем факторы для выбранной строки"', source)
        self.assertNotIn("model_id ==", source)
        self.assertNotIn('"INN"', source)
        self.assertNotIn('"DefMark"', source)
        self.assertNotIn("OpenAI", source)
        self.assertNotIn("API_KEY", source)

    def test_inference_upload_stages_browser_file_and_replaces_only_inference_state(
        self,
    ) -> None:
        from app import streamlit_app
        from app.upload_staging import cleanup_staged_upload

        model = SimpleNamespace(
            summary=SimpleNamespace(
                model_version_id="model-1", model_id="model", feature_ids=("score",)
            )
        )
        old_batch = object()
        state = {
            "dataset_context": object(),
            "loaded_model_version": model,
            "active_model_version_id": "model-1",
            "inference_source_path": "old.csv",
            "inference_snapshot": object(),
            "prediction_batch": old_batch,
            "selected_prediction_row_id": "old-row",
            "local_explanation_evidence": object(),
            "result_interpreter_request": object(),
            "result_interpreter_response": object(),
            "result_interpreter_dispatch_receipt": object(),
            "result_interpreter_error_code": "old-error",
            "result_interpreter_requests_by_role": {"lawyer": object()},
            "result_interpreter_responses_by_role": {"lawyer": object()},
            "result_interpreter_receipts_by_role": {"lawyer": object()},
            "result_interpreter_errors_by_role": {"lawyer": "old-error"},
        }
        upload = _Upload("inference.csv", b"client_id,score\n1,0.1\n")
        streamlit = _InferenceUploadStreamlit(upload=upload, session_state=state)
        state = streamlit.session_state
        workflow = _InferenceUploadWorkflow()
        runtime = SimpleNamespace(
            integration_workflow_service=workflow,
            model_registry=SimpleNamespace(
                get=lambda _model_id: SimpleNamespace(display_name_ru="Model")
            ),
        )
        snapshot = object()

        try:
            with (
                patch.object(streamlit_app, "st", streamlit),
                patch.object(
                    streamlit_app.TabularReader, "read", return_value=snapshot
                ) as read,
                self.assertRaises(_StopRerun),
            ):
                streamlit_app._render_local_model_use_flow(
                    runtime, SimpleNamespace(artifact_id="artifact-1")
                )

            staged = state["prototype_staged_inference_upload"]
            read.assert_called_once_with(staged.local_path)
            self.assertEqual(workflow.predict_calls, [(model, snapshot)])
            self.assertEqual(state["inference_source_path"], str(staged.local_path))
            self.assertIs(state["loaded_model_version"], model)
            self.assertIsNot(state["prediction_batch"], old_batch)
            self.assertIsNone(state["selected_prediction_row_id"])
            self.assertIsNone(state["local_explanation_evidence"])
            self.assertIsNone(state["result_interpreter_request"])
            self.assertIsNone(state["result_interpreter_response"])
            self.assertIsNone(state["result_interpreter_dispatch_receipt"])
            self.assertIsNone(state["result_interpreter_error_code"])
            self.assertEqual(state["result_interpreter_requests_by_role"], {})
            self.assertEqual(state["result_interpreter_responses_by_role"], {})
            self.assertEqual(state["result_interpreter_receipts_by_role"], {})
            self.assertEqual(state["result_interpreter_errors_by_role"], {})
        finally:
            cleanup_staged_upload(state.get("prototype_staged_inference_upload"))

    def test_initial_lawyer_action_calls_only_lawyer_and_renders_all_tabs(self) -> None:
        from app import streamlit_app

        workflow = _RoleUiWorkflow()
        streamlit = _RoleUiStreamlit(
            pressed_key="request-result-interpretation-lawyer",
            session_state={
                "result_interpreter_requests_by_role": {},
                "result_interpreter_responses_by_role": {},
                "result_interpreter_receipts_by_role": {},
                "result_interpreter_errors_by_role": {},
            },
        )

        with patch.object(streamlit_app, "st", streamlit):
            streamlit_app._render_result_interpretation(
                workflow=workflow,
                evidence=object(),
                loaded_model_version=object(),
            )

        self.assertEqual(
            streamlit.tab_labels,
            [
                streamlit_app._RESULT_INTERPRETER_ROLE_LABELS[role]
                for role in streamlit_app.RESULT_INTERPRETER_ROLES
            ],
        )
        self.assertEqual(workflow.prepare_calls, ["lawyer"])
        self.assertEqual(workflow.provider_calls, ["lawyer"])
        self.assertEqual(workflow.provider_calls.count("sales_manager"), 0)
        self.assertEqual(workflow.provider_calls.count("credit_controller"), 0)
        self.assertEqual(workflow.provider_calls.count("information_security"), 0)

    def test_retry_calls_only_the_failed_role(self) -> None:
        from app import streamlit_app

        lawyer_request = SimpleNamespace(recipient_role="lawyer")
        workflow = _RoleUiWorkflow()
        streamlit = _RoleUiStreamlit(
            pressed_key="retry-result-interpretation-lawyer",
            session_state={
                "result_interpreter_requests_by_role": {"lawyer": lawyer_request},
                "result_interpreter_responses_by_role": {
                    "sales_manager": SimpleNamespace(text="existing response"),
                },
                "result_interpreter_receipts_by_role": {},
                "result_interpreter_errors_by_role": {
                    "lawyer": "RESULT_INTERPRETER_CALL_FAILED"
                },
            },
        )

        with patch.object(streamlit_app, "st", streamlit):
            streamlit_app._render_result_interpretation(
                workflow=workflow,
                evidence=object(),
                loaded_model_version=object(),
            )

        self.assertEqual(workflow.prepare_calls, [])
        self.assertEqual(workflow.provider_calls, ["lawyer"])
        self.assertIn(
            "lawyer", streamlit.session_state["result_interpreter_responses_by_role"]
        )
        self.assertIn(
            "sales_manager",
            streamlit.session_state["result_interpreter_responses_by_role"],
        )

    def test_prediction_file_error_explains_missing_features_in_russian(self) -> None:
        from app.streamlit_app import _prediction_file_error_message

        message = _prediction_file_error_message(
            ValueError(
                "Required model feature columns are absent from the inference source: ['Q_A1_norm', 'Q_A2_norm']."
            )
        )

        self.assertEqual(
            message,
            "В файле отсутствуют обязательные признаки модели: Q_A1_norm, Q_A2_norm. "
            "Добавьте эти столбцы и повторите прогноз.",
        )

    def test_prediction_file_error_explains_missing_identifier_in_russian(self) -> None:
        from app.streamlit_app import _prediction_file_error_message

        message = _prediction_file_error_message(
            ValueError(
                "Required identifier column 'client_id' is absent from the inference source."
            )
        )

        self.assertEqual(
            message, "В файле отсутствует обязательный идентификатор «client_id»."
        )

    def test_prediction_file_error_explains_real_physical_header_error(self) -> None:
        from app.streamlit_app import _prediction_file_error_message
        from komus_risk.data import TabularReadError

        message = _prediction_file_error_message(
            TabularReadError(
                "invalid_physical_header", "Physical headers must be unique."
            )
        )

        self.assertIn(
            "\u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043a\u0438 \u0444\u0430\u0439\u043b\u0430",
            message,
        )
        self.assertIn("\u0434\u0443\u0431\u043b\u0438\u043a\u0430\u0442\u044b", message)


if __name__ == "__main__":
    unittest.main()
