"""AnalyzeJob dataclass and in-memory job registry."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

PhaseCallback = Callable[[Dict[str, Any]], None]


@dataclass
class AnalyzeJob:
    job_id: str
    session_id: str
    file_path: str
    dir: Path
    status: str = "pending"
    error: Optional[str] = None
    profile: Dict[str, Any] = field(default_factory=dict)
    profile_rich: Dict[str, Any] = field(default_factory=dict)
    plan: Dict[str, Any] = field(default_factory=dict)
    sub_tables: List[Dict[str, Any]] = field(default_factory=list)
    charts: List[Dict[str, Any]] = field(default_factory=list)
    sections: List[Dict[str, Any]] = field(default_factory=list)
    exec_summary: Optional[str] = None
    key_findings: Optional[str] = None
    domain_brief: str = ""
    clarification_qa: List[Dict[str, Any]] = field(default_factory=list)
    domain_context: str = ""
    depth: str = "standard"
    report_path: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _done_event: threading.Event = field(default_factory=threading.Event)
    _profile_ready: threading.Event = field(default_factory=threading.Event)


class AnalyzeJobRegistry:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="deep_analyze")
        self.fanout = ThreadPoolExecutor(max_workers=8, thread_name_prefix="deep_analyze_child")
        self._jobs: Dict[str, AnalyzeJob] = {}
        self._lock = threading.Lock()

    def submit(self, job: AnalyzeJob, runner: Callable[[AnalyzeJob], None]) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
        self._executor.submit(runner, job)

    def get(self, job_id: str) -> Optional[AnalyzeJob]:
        return self._jobs.get(job_id)
