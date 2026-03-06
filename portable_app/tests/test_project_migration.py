import unittest

from app.core.project_migration import migrate_project_state


class ProjectMigrationTests(unittest.TestCase):
    def test_migrates_v2_events_with_defaults(self):
        state_v2 = {
            "schema_version": 2,
            "app_version": "1.0.0",
            "events": [{"id": "sd_event_001", "masks_ref": "events/sd_event_001/masks.npz"}],
            "image_manifest": {"ref": "images.json"},
        }
        migrated = migrate_project_state(state_v2)
        self.assertEqual(migrated["schema_version"], 3)
        ev = migrated["events"][0]
        self.assertIn("masks_draft_ref", ev)
        self.assertIn("propagation_completed", ev)
        self.assertIn("analysis_output_dir", ev)
        self.assertTrue(ev["propagation_completed"])

    def test_preserves_unknown_keys(self):
        state_v2 = {
            "schema_version": 2,
            "app_version": "1.0.0",
            "events": [{"id": "sd_event_001", "custom_field": {"x": 1}}],
            "image_manifest": {"ref": "images.json"},
        }
        migrated = migrate_project_state(state_v2)
        self.assertEqual(migrated["events"][0]["custom_field"], {"x": 1})


if __name__ == "__main__":
    unittest.main()
