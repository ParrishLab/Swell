import unittest

from sdapp.analysis.core.propagation_progress import PropagationProgressLogger


class PropagationProgressLoggerTests(unittest.TestCase):
    def test_start_tick_finish_emits_progress_and_status(self):
        progress_lines = []
        logs = []
        logger = PropagationProgressLogger(
            write_progress=progress_lines.append,
            log_info=lambda c, m: logs.append(("info", c, m)),
            log_success=lambda c, m: logs.append(("success", c, m)),
            log_warn=lambda c, m: logs.append(("warn", c, m)),
            log_error=lambda c, m: logs.append(("error", c, m)),
            bar_width=10,
        )

        run_id = logger.start(total_steps=4, label="Propagation")
        logger.tick(increment=1, run_id=run_id)
        logger.finish(status="complete", run_id=run_id)

        self.assertTrue(progress_lines)
        self.assertIn("[INFO][Propagation]", progress_lines[0])
        self.assertTrue(any("[INFO][Propagation]" in line for line in progress_lines))
        self.assertIn(("success", "Propagation", "Propagation complete"), logs)

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
