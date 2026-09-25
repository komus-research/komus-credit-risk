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
        self.assertNotIn("model_id ==", source)
        self.assertNotIn('"INN"', source)
        self.assertNotIn('"DefMark"', source)


if __name__ == "__main__":
    unittest.main()
