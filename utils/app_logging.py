#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In-memory log queue used by the web UI polling endpoints."""

import logging
import threading


class LogStore:
    """内存日志环形存储，供前端按增量轮询。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = []
        self._next_id = 1

    def add(self, text):
        with self._lock:
            eid = self._next_id
            self._next_id += 1
            self._entries.append((eid, text))
            return eid

    def since(self, n):
        with self._lock:
            return [(eid, t) for eid, t in self._entries if eid > n]

    def all(self):
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._next_id = 1


class QueueLogHandler(logging.Handler):
    def __init__(self, store):
        super().__init__()
        self._store = store

    def emit(self, record):
        try:
            self._store.add(self.format(record))
        except Exception:
            pass


log_store = LogStore()


def setup_logging():
    handler = QueueLogHandler(log_store)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
