import unittest

import numpy as np

from swell.analysis.core.project_migration import migrate_project_state


class ProjectMigrationTests(unittest.TestCase):
    def test_migrates_v2_events_with_defaults(self):
        state_v2 = {
            "schema_version": 2,
            "app_version": "1.0.0",
            "events": [{"id": "sd_event_001", "masks_ref": "events/sd_event_001/masks.npz"}],
            "image_manifest": {"ref": "images.json"},
        }
        migrated = migrate_project_state(state_v2)
        self.assertEqual(migrated["schema_version"], 6)
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
        self.assertFalse(migrated["events"][0]["propagation_completed"])

    def test_v2_migration_uses_loaded_masks_to_mark_propagation_complete(self):
        state_v2 = {
            "schema_version": 2,
            "events": [{"id": "sd_event_001"}],
            "image_manifest": {"ref": "images.json"},
        }

        migrated = migrate_project_state(
            state_v2,
            event_payloads={"sd_event_001": {"masks": np.ones((1, 2, 2), dtype=np.uint8)}},
        )

        self.assertTrue(migrated["events"][0]["propagation_completed"])

    def test_v2_migration_does_not_treat_empty_loaded_masks_as_complete(self):
        state_v2 = {
            "schema_version": 2,
            "events": [{"id": "sd_event_001", "masks_ref": "events/sd_event_001/masks.npz"}],
            "image_manifest": {"ref": "images.json"},
        }

        migrated = migrate_project_state(
            state_v2,
            event_payloads={"sd_event_001": {"masks": np.asarray([], dtype=np.uint8)}},
        )

        self.assertFalse(migrated["events"][0]["propagation_completed"])

    def test_migrates_v3_to_latest_without_prompt_changes(self):
        state_v3 = {
            "schema_version": 3,
            "app_version": "1.0.0",
            "events": [{"id": "sd_event_001", "prompts_ref": "events/sd_event_001/prompts.json"}],
            "image_manifest": {"ref": "images.json"},
        }
        migrated = migrate_project_state(state_v3)
        self.assertEqual(migrated["schema_version"], 6)
        self.assertEqual(migrated["events"], state_v3["events"])

    def test_migrates_v4_to_latest_additively(self):
        state_v4 = {
            "schema_version": 4,
            "app_version": "1.0.0",
            "events": [{"id": "sd_event_001", "prompts_ref": "events/sd_event_001/prompts.json"}],
            "image_manifest": {"ref": "images.json"},
        }

        migrated = migrate_project_state(state_v4)

        self.assertEqual(migrated["schema_version"], 6)
        self.assertEqual(migrated["events"], state_v4["events"])

    def test_migrates_v5_to_v6_additively(self):
        state_v5 = {
            "schema_version": 5,
            "app_version": "1.0.0",
            "events": [{"id": "sd_event_001", "prompts_ref": "events/sd_event_001/prompts.json"}],
            "image_manifest": {"ref": "images.json"},
        }

        migrated = migrate_project_state(state_v5)

        self.assertEqual(migrated["schema_version"], 6)
        self.assertEqual(migrated["events"], state_v5["events"])


if __name__ == "__main__":
    unittest.main()
