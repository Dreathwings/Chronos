import unittest

from app.scheduler import suggest_schedule_recovery


class SuggestionHintTestCase(unittest.TestCase):
    def test_missing_class_suggestion(self) -> None:
        hints = suggest_schedule_recovery(
            "Associez au moins une classe au cours avant de planifier.",
            None,
        )
        self.assertTrue(any("classe" in hint.lower() for hint in hints))

    def test_room_capacity_suggestion(self) -> None:
        hints = suggest_schedule_recovery(
            "Aucune salle n'atteint la capacité requise.",
            None,
        )
        self.assertTrue(any("salle" in hint.lower() for hint in hints))
