import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("TAVILY_API_KEY", "test-key")

from tools import buy_stock, calculator, save_note


class CalculatorTests(unittest.TestCase):
    def test_arithmetic_and_math_functions(self):
        result = calculator.invoke({"expression": "sqrt(144) + 25 * 4"})

        self.assertEqual(result, "112.0")

    def test_collection_function(self):
        result = calculator.invoke({"expression": "sum([1, 2, 3, 4])"})

        self.assertEqual(result, "10")

    def test_unsafe_object_access_is_rejected(self):
        result = calculator.invoke(
            {"expression": "().__class__.__base__.__subclasses__()"}
        )

        self.assertTrue(result.startswith("Calculation error:"))

    def test_large_exponent_is_rejected(self):
        result = calculator.invoke({"expression": "2 ** 1000"})

        self.assertEqual(result, "Calculation error: Exponent is too large.")


class ToolBehaviorTests(unittest.TestCase):
    def test_stock_purchase_is_explicitly_simulated(self):
        result = buy_stock.invoke({"symbol": "aapl", "quantity": 2})

        self.assertIn("Simulated purchase completed", result)
        self.assertIn("No broker was contacted", result)

    def test_invalid_stock_quantity_is_rejected(self):
        result = buy_stock.invoke({"symbol": "AAPL", "quantity": 0})

        self.assertEqual(result, "Quantity must be a positive whole number.")

    def test_note_filename_cannot_escape_notes_directory(self):
        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary_directory:
            try:
                os.chdir(temporary_directory)
                result = save_note.invoke(
                    {"filename": "../approved.txt", "content": "approved"}
                )
                note_path = Path("notes/approved.txt")

                self.assertEqual(result, f"Saved note to {note_path}.")
                self.assertEqual(note_path.read_text(encoding="utf-8"), "approved")
                self.assertFalse(Path("../approved.txt").exists())
            finally:
                os.chdir(original_directory)

    def test_note_uses_configured_data_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(os.environ, {"APP_DATA_DIR": temporary_directory}):
                result = save_note.invoke(
                    {"filename": "deployment.txt", "content": "persistent"}
                )

            note_path = Path(temporary_directory) / "notes" / "deployment.txt"
            self.assertEqual(result, f"Saved note to {note_path}.")
            self.assertEqual(note_path.read_text(encoding="utf-8"), "persistent")


if __name__ == "__main__":
    unittest.main()