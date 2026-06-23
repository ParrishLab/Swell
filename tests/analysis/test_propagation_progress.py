import unittest

from swell.analysis.core.propagation_progress import PropagationProgressLogger


class PropagationProgressLoggerTests(unittest.TestCase):
    def test_start_tick_finish_emits_progress_and_status(self):
        progress_lines = []
        logs = []
        updates = []
        logger = PropagationProgressLogger(
            write_progress=progress_lines.append,
            log_info=lambda c, m: logs.append(("info", c, m)),
            log_success=lambda c, m: logs.append(("success", c, m)),
            log_warn=lambda c, m: logs.append(("warn", c, m)),
            log_error=lambda c, m: logs.append(("error", c, m)),
            on_update=lambda **payload: updates.append(payload),
            bar_width=10,
        )

        run_id = logger.start(total_steps=4, label="Propagation", prop_start=2, prop_end=8, anchor=4)
        logger.tick(increment=1, run_id=run_id, phase="forward", direction="forward", phase_done=1, phase_total=3)
        logger.finish(status="complete", run_id=run_id)

        self.assertTrue(progress_lines)
        self.assertIn("[INFO][Propagation]", progress_lines[0])
        self.assertTrue(any("[INFO][Propagation]" in line for line in progress_lines))
        self.assertIn(("success", "Propagation", "Propagation complete"), logs)
        assert updates[0]["status"] == "started"
        assert updates[0]["prop_start"] == 2
        assert updates[0]["prop_end"] == 8
        assert updates[0]["anchor"] == 4
        assert any(update["status"] == "progress" for update in updates)
        progress_update = next(update for update in updates if update["status"] == "progress")
        assert progress_update["direction"] == "forward"
        assert progress_update["phase_done"] == 1
        assert progress_update["phase_total"] == 3
        assert progress_update["forward_done"] == 1
        assert progress_update["forward_total"] == 3
        assert progress_update["backward_done"] == 0
        assert progress_update["backward_total"] == 0
        assert updates[-1]["status"] == "complete"
        assert updates[-1]["active"] is False

    def test_forward_progress_is_preserved_when_backward_phase_starts(self):
        updates = []
        logger = PropagationProgressLogger(
            write_progress=lambda _line: None,
            log_info=lambda _c, _m: None,
            log_success=lambda _c, _m: None,
            log_warn=lambda _c, _m: None,
            log_error=lambda _c, _m: None,
            on_update=lambda **payload: updates.append(payload),
        )

        run_id = logger.start(total_steps=8, label="Propagation", prop_start=37, prop_end=54, anchor=49)
        logger.tick(run_id=run_id, phase="forward", direction="forward", phase_done=6, phase_total=6)
        logger.tick(run_id=run_id, phase="backward", direction="backward", phase_done=1, phase_total=2)

        backward_update = updates[-1]
        assert backward_update["direction"] == "backward"
        assert backward_update["forward_done"] == 6
        assert backward_update["forward_total"] == 6
        assert backward_update["backward_done"] == 1
        assert backward_update["backward_total"] == 2

    def test_ignores_old_run_id(self):
        progress_lines = []
        logs = []
        logger = PropagationProgressLogger(
            write_progress=progress_lines.append,
            log_info=lambda c, m: logs.append(("info", c, m)),
            log_success=lambda c, m: logs.append(("success", c, m)),
            log_warn=lambda c, m: logs.append(("warn", c, m)),
            log_error=lambda c, m: logs.append(("error", c, m)),
        )
        run_id = logger.start(total_steps=2)
        logger.tick(increment=1, run_id=run_id + 1)
        logger.finish(status="stopped", run_id=run_id + 1)
        self.assertEqual(len(progress_lines), 1)
        self.assertEqual(logs, [])


if __name__ == "__main__":
    unittest.main()
