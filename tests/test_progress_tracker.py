import unittest

from app import create_app, db
from app.progress import ScheduleProgressTracker, progress_registry
from config import TestConfig


class ProgressTrackerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_tracker_cancel_snapshot(self) -> None:
        tracker = ScheduleProgressTracker("Test")
        tracker.initialise(4)
        self.assertFalse(tracker.should_abort())

        tracker.request_cancel("Stop")
        self.assertTrue(tracker.should_abort())

        snapshot = tracker.snapshot()
        self.assertTrue(snapshot.cancel_requested)
        self.assertEqual(snapshot.state, "running")

        tracker.mark_cancelled("Fin")
        cancelled_snapshot = tracker.snapshot()
        self.assertEqual(cancelled_snapshot.state, "cancelled")
        self.assertTrue(cancelled_snapshot.finished)
        self.assertTrue(cancelled_snapshot.cancel_requested)

    def test_cancel_endpoint_marks_tracker(self) -> None:
        tracker = progress_registry.create("Annulation test")
        try:
            client = self.app.test_client()
            base_path = self.app.config.get("URL_PREFIX", "") or ""
            response = client.post(
                f"{base_path}/generation/progress/{tracker.job_id}/cancel"
            )
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertTrue(payload.get("cancel_requested"))

            stored = progress_registry.get(tracker.job_id)
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertTrue(stored.cancel_requested())
        finally:
            progress_registry.remove(tracker.job_id)

    def test_status_endpoint_reports_cancel_flag(self) -> None:
        tracker = progress_registry.create("Status test")
        try:
            tracker.initialise(2)
            tracker.request_cancel("Stop")
            client = self.app.test_client()
            base_path = self.app.config.get("URL_PREFIX", "") or ""
            response = client.get(
                f"{base_path}/generation/progress/{tracker.job_id}"
            )
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertTrue(payload.get("cancel_requested"))
        finally:
            progress_registry.remove(tracker.job_id)

