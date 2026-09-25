from __future__ import annotations

from pathlib import Path
import unittest


class StreamlitIntegrationUiTests(unittest.TestCase):
    def test_result_ui_uses_facade_and_dynamic_prediction_identifier(self) -> None:
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")

        self.assertIn("workflow.save_model(", source)
        self.assertIn("workflow.predict(", source)
        self.assertIn("workflow.explain(", source)
        self.assertIn("workflow.prepare_interpretation(", source)
        self.assertIn("workflow.interpret(", source)
        self.assertIn("Объяснить результат простыми словами", source)
        self.assertIn("Автоматическое текстовое объяснение отключено политикой передачи данных.", source)
        self.assertIn("Текстовое объяснение разрешено, но не настроено в текущем запуске.", source)
        self.assertIn("Повторить объяснение", source)
        self.assertIn("Текстовое объяснение сейчас недоступно.", source)
        self.assertIn("не является кредитным решением", source)
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
        self.assertNotIn("OpenAI", source)
        self.assertNotIn("API_KEY", source)

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


    def test_prediction_file_error_explains_real_physical_header_error(self) -> None:
        from app.streamlit_app import _prediction_file_error_message
        from komus_risk.data import TabularReadError

        message = _prediction_file_error_message(
            TabularReadError("invalid_physical_header", "Physical headers must be unique.")
        )

        self.assertIn("\u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043a\u0438 \u0444\u0430\u0439\u043b\u0430", message)
        self.assertIn("\u0434\u0443\u0431\u043b\u0438\u043a\u0430\u0442\u044b", message)


if __name__ == "__main__":
    unittest.main()
