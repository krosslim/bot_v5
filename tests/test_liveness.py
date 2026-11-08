"""Метка «жив» для healthcheck контейнера: python -m unittest discover -s tests -t ."""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from src.infrastructure import liveness

ROOT = Path(__file__).resolve().parents[1]


class LivenessTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "alive"

    def tearDown(self):
        self.dir.cleanup()

    def test_fresh_stale_missing(self):
        self.assertFalse(liveness.is_alive(self.path))
        liveness.beat(self.path)
        self.assertTrue(liveness.is_alive(self.path))
        self.assertFalse(liveness.is_alive(self.path, now=time.time() + liveness.MAX_AGE + 1))
        liveness.clear(self.path)
        self.assertFalse(liveness.is_alive(self.path))
        liveness.clear(self.path)   # повторная очистка не падает

    def test_beat_forever_refreshes(self):
        async def run():
            task = asyncio.create_task(liveness.beat_forever(self.path, every=0.01))
            await asyncio.sleep(0.05)
            first = self.path.stat().st_mtime_ns
            await asyncio.sleep(0.05)
            task.cancel()
            return first, self.path.stat().st_mtime_ns
        first, last = asyncio.run(run())
        self.assertGreaterEqual(last, first)
        self.assertTrue(liveness.is_alive(self.path))

    def test_health_script(self):
        """health.py: код 0 при свежей метке, 1 без неё; без сети и тяжёлых импортов — быстро"""
        env = {**os.environ, "LIVENESS_FILE": str(self.path)}
        run = lambda: subprocess.run([sys.executable, "health.py"], cwd=ROOT, env=env, capture_output=True, text=True,
                                     timeout=10)
        self.assertEqual(run().returncode, 1)
        liveness.beat(self.path)
        started = time.monotonic()
        self.assertEqual(run().returncode, 0)
        self.assertLess(time.monotonic() - started, 3)


if __name__ == "__main__":
    unittest.main()
