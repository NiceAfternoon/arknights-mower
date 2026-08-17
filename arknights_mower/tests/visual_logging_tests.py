import logging
import tempfile
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import patch

from arknights_mower.utils import config
from arknights_mower.utils.graph import SceneGraphSolver
from arknights_mower.utils.log import (
    Handler,
    SceneSnapshotStore,
    get_latest_scene_snapshot,
    publish_scene_snapshot,
)
from arknights_mower.utils.recognize import publish_scene_result
from arknights_mower.utils.scene import Scene
from arknights_mower.utils.visual_facts import RepresentativeVisualFacts, VisualFact


class SceneSnapshotContractTests(unittest.TestCase):
    def test_publish_returns_only_after_snapshot_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SceneSnapshotStore(Path(tmp_dir))

            filename = store.publish(101, b"scene-bytes")

            self.assertEqual((Path(tmp_dir) / filename).read_bytes(), b"scene-bytes")
            self.assertEqual(store.latest_filename, filename)

    def test_publish_keeps_the_same_scene_silent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SceneSnapshotStore(Path(tmp_dir))
            first_filename = store.publish(101, b"first-scene")

            second_filename = store.publish(101, b"same-scene")

            self.assertIsNone(second_filename)
            self.assertEqual(store.latest_filename, first_filename)
            self.assertEqual(len(list(Path(tmp_dir).iterdir())), 1)

    def test_latest_snapshot_is_owned_by_scene_publication(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SceneSnapshotStore(Path(tmp_dir))

            with patch("arknights_mower.utils.log.scene_snapshot_store", store):
                filename = publish_scene_snapshot(101, b"scene")

                self.assertEqual(get_latest_scene_snapshot(), filename)


class WebUILogProjectionTests(unittest.TestCase):
    def test_scene_result_is_logged_after_its_snapshot_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SceneSnapshotStore(Path(tmp_dir))

            def assert_snapshot_is_ready(_message, *_args, **kwargs):
                filename = kwargs["extra"]["screenshot"]
                self.assertEqual((Path(tmp_dir) / filename).read_bytes(), b"scene")

            with (
                patch("arknights_mower.utils.log.scene_snapshot_store", store),
                patch(
                    "arknights_mower.utils.recognize.logger.info",
                    side_effect=assert_snapshot_is_ready,
                ) as log_info,
            ):
                filename = publish_scene_result(
                    101,
                    "index",
                    b"scene",
                    (VisualFact("index_nav", "matched", 0.95, 0.90, 8),),
                )

            log_info.assert_called_once_with(
                "场景识别完成：operation=%s result=%s representatives=%s",
                "scene",
                "index",
                "index_nav|matched|0.9500|0.9000|8",
                extra={"screenshot": filename},
            )

    def test_snapshot_failure_does_not_change_the_scene_result_contract(self):
        with (
            patch(
                "arknights_mower.utils.recognize.publish_scene_snapshot",
                side_effect=RuntimeError("snapshot writer stopped"),
            ),
            patch("arknights_mower.utils.recognize.logger.error") as log_error,
        ):
            filename = publish_scene_result(101, "index", b"scene")

        self.assertIsNone(filename)
        log_error.assert_called_once_with(
            "场景快照写入失败：operation=%s result=%s",
            "scene_snapshot",
            "failed",
            exc_info=True,
        )
        self.assertNotIn("下一步", log_error.call_args.args[0])

    def test_same_scene_does_not_emit_another_refresh_record(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SceneSnapshotStore(Path(tmp_dir))
            with (
                patch("arknights_mower.utils.log.scene_snapshot_store", store),
                patch("arknights_mower.utils.recognize.logger.info") as log_info,
            ):
                publish_scene_result(101, "index", b"first")
                publish_scene_result(101, "index", b"second")

        log_info.assert_called_once()

    def test_scene_change_record_carries_its_completed_snapshot(self):
        record = logging.LogRecord(
            "scene", logging.INFO, __file__, 1, "operation=scene result=index", (), None
        )
        record.asctime = "2026-08-15 12:00:00"
        record.message = record.getMessage()
        record.screenshot = "123.jpg"
        queue = Queue()

        with patch.object(config, "log_queue", queue):
            Handler().emit(record)

        self.assertEqual(
            queue.get_nowait(),
            {
                "data": "2026-08-15 12:00:00 INFO operation=scene result=index",
                "screenshot": "123.jpg",
            },
        )


class RepresentativeVisualFactTests(unittest.TestCase):
    def test_snapshot_is_deduplicated_and_bounded_to_declared_representatives(self):
        facts = RepresentativeVisualFacts()
        samples = [
            VisualFact("a", "missed", 0.60, 0.90, 4),
            VisualFact("b", "missed", 0.80, 0.90, 5),
            VisualFact("c", "missed", 0.85, 0.90, 6),
            VisualFact("slow", "missed", 0.10, 0.90, 100),
            VisualFact("missing", "missing", None, None, 7),
            VisualFact("selected", "matched", 0.95, 0.90, 8),
        ]
        for fact in samples:
            facts.add(fact)
        facts.add(VisualFact("b", "missed", 0.80, 0.90, 5))

        snapshot = facts.snapshot()

        self.assertEqual(
            [fact.candidate for fact in snapshot],
            ["selected", "c", "b", "slow", "missing"],
        )
        self.assertLessEqual(len(snapshot), 6)


class SceneNavigationResultTests(unittest.TestCase):
    def test_same_navigation_state_stays_silent(self):
        solver = SceneGraphSolver.__new__(SceneGraphSolver)

        with (
            patch.object(solver, "scene", return_value=Scene.INDEX),
            patch.object(solver, "scene_graph_navigation") as navigate,
            patch("arknights_mower.utils.graph.logger.info") as log_info,
        ):
            solver.back_to_index()

        navigate.assert_not_called()
        log_info.assert_not_called()

    def test_aborted_navigation_does_not_emit_a_success_result(self):
        solver = SceneGraphSolver.__new__(SceneGraphSolver)

        with (
            patch.object(solver, "scene", return_value=Scene.UNKNOWN),
            patch.object(solver, "scene_graph_navigation", return_value=False),
            patch("arknights_mower.utils.graph.logger.info") as log_info,
        ):
            solver.back_to_index()

        log_info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
