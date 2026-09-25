from __future__ import annotations

from pathlib import Path
import unittest


class StreamlitIntegrationUiTests(unittest.TestCase):
    def test_result_ui_uses_facade_and_dynamic_prediction_identifier(self) -> None:
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")

        self.assertIn("workflow.save_model(", source)
        self.assertIn("workflow.predict(", source)
        self.assertIn("workflow.explain(", source)
        self.assertIn("prediction_batch.identifier_column", source)
        self.assertIn("set_inference_source_path(st.session_state, selected)", source)
        self.assertIn("set_inference_source_path(st.session_state, source_path)", source)
        self.assertIn('"Алгоритм"', source)
        self.assertIn('"Готовим модель для прогноза"', source)
        self.assertIn('"Модель готова для прогноза"', source)
        self.assertIn('"Выберите файл с организациями, для которых нужно получить прогноз.', source)
        self.assertIn('"Проверяем файл и рассчитываем прогноз"', source)
        self.assertIn('"Рассчитываем факторы для выбранной строки"', source)
        self.assertNotIn("model_id ==", source)
        self.assertNotIn('"INN"', source)
        self.assertNotIn('"DefMark"', source)

    def test_prediction_file_error_explains_missing_features_in_russian(self) -> None:
        from app.streamlit_app import _prediction_file_error_message

        message = _prediction_file_error_message(
            ValueError("Required model feature columns are absent from the inference source: ['Q_A1_norm', 'Q_A2_norm'].")
        )

        self.assertEqual(
            message,
            "В файле отсутствуют обязательные признаки модели: Q_A1_norm, Q_A2_norm. "
            "Добавьте эти столбцы и повторите прогноз.",
        )

    def test_prediction_file_error_explains_missing_identifier_in_russian(self) -> None:
        from app.streamlit_app import _prediction_file_error_message

        message = _prediction_file_error_message(
            ValueError("Required identifier column 'client_id' is absent from the inference source.")
        )

        self.assertEqual(message, "В файле отсутствует обязательный идентификатор «client_id».")


if __name__ == "__main__":
    unittest.main()
