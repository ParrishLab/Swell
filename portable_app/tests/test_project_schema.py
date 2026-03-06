import unittest

from app.core.project_schema import SCHEMA_VERSION, default_project_state, validate_project_state


class ProjectSchemaTests(unittest.TestCase):
    def test_defaults_include_required_fields(self):
        state = default_project_state("x.y.z")
        validate_project_state(state)
        self.assertEqual(state["schema_version"], SCHEMA_VERSION)
        self.assertEqual(state["app_version"], "x.y.z")

    def test_validate_rejects_missing_keys(self):
        with self.assertRaises(ValueError):
            validate_project_state({"schema_version": 2})

    def test_validate_event_field_types(self):
        state = default_project_state("x.y.z")
        state["events"] = [
            {
                "id": "sd_event_001",
                "masks_ref": "events/sd_event_001/masks.npz",
                "prompts_ref": "events/sd_event_001/prompts.json",
                "masks_draft_ref": None,
                "propagation_completed": True,
                "analysis_output_dir": None,
            }
        ]
        validate_project_state(state)


if __name__ == "__main__":
    unittest.main()
