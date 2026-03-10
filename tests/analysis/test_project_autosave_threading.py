import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path

from sdapp.analysis.core.project_autosave import AutosaveSnapshot, ProjectAutosaveManager


class ProjectAutosaveThreadingTests(unittest.TestCase):
    def test_snapshot_runs_on_dispatched_main_and_writes_serially(self):
        with tempfile.TemporaryDirectory() as tmp:
            main_queue: queue.Queue[callable | None] = queue.Queue()
            main_thread_name = "autosave-main-loop"
            stop_main = threading.Event()
            snapshot_threads = []
            write_threads = []
            active_writes = {"count": 0, "max": 0}
            writes = []

            def main_loop():
                threading.current_thread().name = main_thread_name
                while not stop_main.is_set():
                    fn = main_queue.get()
                    if fn is None:
                        break
                    fn()
                    main_queue.task_done()

            main_loop_thread = threading.Thread(target=main_loop, daemon=True)
            main_loop_thread.start()

            def dispatch(fn):
                main_queue.put(fn)

            def snapshot():
                snapshot_threads.append(threading.current_thread().name)
                return AutosaveSnapshot(
                    project_state={},
                    images_manifest={},
                    roi_data={},
                    event_payloads={},
                    embed_images=False,
                )

            lock = threading.Lock()

            def writer(_snapshot: AutosaveSnapshot, path: Path):
                with lock:
                    active_writes["count"] += 1
                    active_writes["max"] = max(active_writes["max"], active_writes["count"])
                write_threads.append(threading.current_thread().name)
                writes.append(path.name)
                path.write_text("ok", encoding="utf-8")
                time.sleep(0.02)
                with lock:
                    active_writes["count"] -= 1

            mgr = ProjectAutosaveManager(
                snapshot_callable=snapshot,
                write_callable=writer,
                autosave_dir=tmp,
                max_slots=3,
                debounce_sec=0.03,
                dispatch_to_main=dispatch,
            )
            for _ in range(4):
                mgr.schedule("burst")
                time.sleep(0.08)
            time.sleep(0.2)
            mgr.stop()
            stop_main.set()
            main_queue.put(None)
            main_loop_thread.join(timeout=1.0)

            self.assertGreaterEqual(len(writes), 1)
            self.assertTrue(all(name == main_thread_name for name in snapshot_threads))
            self.assertTrue(all(name != main_thread_name for name in write_threads))
            self.assertEqual(active_writes["max"], 1)

    def test_debounce_coalesces_burst(self):
        with tempfile.TemporaryDirectory() as tmp:
            writes = []

            def snapshot():
                return AutosaveSnapshot(
                    project_state={},
                    images_manifest={},
                    roi_data={},
                    event_payloads={},
                    embed_images=False,
                )

            def writer(_snapshot: AutosaveSnapshot, path: Path):
                writes.append(path.name)
                path.write_text("ok", encoding="utf-8")

            mgr = ProjectAutosaveManager(snapshot, writer, tmp, debounce_sec=0.1)
            for _ in range(6):
                mgr.schedule("rapid")
                time.sleep(0.02)
            time.sleep(0.25)
            mgr.stop()
            self.assertEqual(len(writes), 1)


if __name__ == "__main__":
    unittest.main()
