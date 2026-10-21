"""
Raw block writer. Abbas, Oct 21 2026 (new).

Why: mea_device.py only keeps the last window in memory and reads the 60 analog streams.
For the benchmark we need the WHOLE recording on disk, including the digital / sideband
streams, because the sideband bit marks exactly when each pulse played.
Format: <name>.bin = int32, sample-major (n_samples x n_streams); <name>.json = metadata.
A writer thread does the disk I/O so the DLL callback never blocks.
"""
import json
import queue
import threading
import time

import numpy as np


class RawBlockWriter:
    def __init__(self, path_prefix, fs, n_streams, meta=None):
        self.prefix = str(path_prefix)
        self.fs = fs
        self.n_streams = n_streams
        self.meta = dict(meta or {})
        self.samples = 0
        self._q = queue.Queue()
        self._f = open(self.prefix + ".bin", "wb")
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        self.t_start = time.perf_counter()

    def push(self, chunk):
        """chunk: (n_streams, n_frames) int32."""
        self.samples += chunk.shape[1]
        self._q.put(np.ascontiguousarray(chunk.T, dtype=np.int32))

    def _run(self):
        while True:
            c = self._q.get()
            if c is None:
                break
            self._f.write(c.tobytes())

    def close(self, extra_meta=None):
        self._q.put(None)
        self._t.join()
        self._f.close()
        m = {"fs": self.fs, "n_streams": self.n_streams, "n_samples": self.samples, "dtype": "int32",
             "layout": "sample-major", "analog_streams": list(range(60)), "wall_seconds": time.perf_counter() - self.t_start}
        m.update(self.meta)
        m.update(extra_meta or {})
        with open(self.prefix + ".json", "w") as f:
            json.dump(m, f, indent=1)
        return m
