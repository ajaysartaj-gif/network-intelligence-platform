"""
core/discovery/range_scanner.py
================================
Bounded-concurrency network range scanner.

Engineering choices, and why:

  - TCP-connect probing is PRIMARY, not ICMP ping. The existing
    `_icmp_ping()` in device_discovery.py shells out to the system
    `ping` binary via subprocess — that's fine for a handful of
    targeted pings, but spawning a subprocess per host does not scale
    to scanning hundreds of thousands or millions of addresses (process
    spawn overhead alone would dominate). A raw-socket ICMP approach
    would be fast but needs root/raw-socket privileges on macOS/Linux,
    which we don't want to require. A plain TCP `socket.create_connection`
    attempt needs no special privileges, is cheap, and — since the vast
    majority of devices worth discovering (routers, switches, firewalls,
    APs) have at least one of SSH/Telnet/HTTP/HTTPS open for management —
    is also a reliable liveness signal in practice.

  - Bounded in-flight concurrency, NOT executor.map() over the full
    range. ThreadPoolExecutor.map() eagerly creates a Future for every
    item up front; for a /8 (16.7M addresses) that means 16.7 million
    Future objects in memory at once. Instead we keep a fixed-size
    window of in-flight probes (default 300) and only submit the next
    address once a slot frees up — memory usage stays flat regardless
    of whether the range is a /24 or a full /8.

  - Cancellable. A `threading.Event` is checked between submissions so
    a multi-hour /8 scan can be stopped cleanly without leaking threads.

  - Progress is a plain dataclass, not a queue/callback the UI must
    consume synchronously — Streamlit's rerun model polls state on
    every interaction, so a simple mutable progress object the UI
    reads from session_state fits naturally.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from core.discovery.network_ranges import iter_hosts, host_count

logger = logging.getLogger("NetBrain.Discovery.Scanner")

DEFAULT_PORTS = (22, 23, 80, 443)
DEFAULT_CONCURRENCY = 300
DEFAULT_TIMEOUT_SEC = 0.4
DEFAULT_MAX_IN_FLIGHT = 1000


# ═══════════════════════════════════════════════════════════════════════════════
# Progress tracking
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScanProgress:
    job_id: str
    total_addresses: int
    scanned: int = 0
    found: List[str] = field(default_factory=list)
    status: str = "running"        # "running" | "done" | "cancelled" | "error"
    error: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: Optional[str] = None

    def percent(self) -> float:
        if self.total_addresses <= 0:
            return 100.0
        return min(100.0, 100.0 * self.scanned / self.total_addresses)

    def elapsed_sec(self) -> float:
        try:
            start = datetime.fromisoformat(self.started_at)
            end = (
                datetime.fromisoformat(self.finished_at)
                if self.finished_at else datetime.utcnow()
            )
            return (end - start).total_seconds()
        except Exception:
            return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Probe function
# ═══════════════════════════════════════════════════════════════════════════════

def _probe_host(ip: str, ports: tuple, timeout: float) -> bool:
    """Return True if any of the given TCP ports accept a connection."""
    for port in ports:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# RangeScanner — orchestrates bounded-concurrency scans
# ═══════════════════════════════════════════════════════════════════════════════

class RangeScanner:
    """
    Manages background range-scan jobs. One instance is shared (singleton)
    so the UI can poll progress across Streamlit reruns.
    """

    def __init__(self):
        self._jobs: Dict[str, ScanProgress] = {}
        self._cancel_flags: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start_scan(
        self,
        cidrs: List[str],
        on_found: Optional[Callable[[str], None]] = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        ports: tuple = DEFAULT_PORTS,
        max_in_flight: int = DEFAULT_MAX_IN_FLIGHT,
        exclude_cidrs: Optional[List[str]] = None,
    ) -> str:
        """
        Kick off a background scan across one or more CIDR blocks.
        Returns a job_id for polling via get_progress()/cancel().
        """
        job_id = uuid.uuid4().hex[:12]
        total = sum(host_count(c) for c in cidrs)

        progress = ScanProgress(job_id=job_id, total_addresses=total)
        cancel_event = threading.Event()

        with self._lock:
            self._jobs[job_id] = progress
            self._cancel_flags[job_id] = cancel_event

        def _host_generator():
            for cidr in cidrs:
                yield from iter_hosts(cidr, exclude_cidrs=exclude_cidrs)

        thread = threading.Thread(
            target=self._run_scan,
            args=(job_id, _host_generator(), on_found, concurrency,
                  timeout_sec, ports, max_in_flight, cancel_event),
            daemon=True, name=f"RangeScan-{job_id}",
        )
        thread.start()
        return job_id

    def _run_scan(
        self,
        job_id: str,
        host_gen,
        on_found: Optional[Callable[[str], None]],
        concurrency: int,
        timeout_sec: float,
        ports: tuple,
        max_in_flight: int,
        cancel_event: threading.Event,
    ) -> None:
        progress = self._jobs[job_id]
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                in_flight: Dict = {}

                # Prime the initial window
                for _ in range(min(max_in_flight, concurrency * 3)):
                    ip = next(host_gen, None)
                    if ip is None:
                        break
                    fut = executor.submit(_probe_host, ip, ports, timeout_sec)
                    in_flight[fut] = ip

                while in_flight:
                    if cancel_event.is_set():
                        progress.status = "cancelled"
                        break

                    done, _ = wait(
                        list(in_flight.keys()),
                        timeout=2.0,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        continue  # nothing finished yet within the wait window

                    for fut in done:
                        ip = in_flight.pop(fut)
                        progress.scanned += 1
                        try:
                            alive = fut.result()
                        except Exception:
                            alive = False
                        if alive:
                            progress.found.append(ip)
                            if on_found:
                                try:
                                    on_found(ip)
                                except Exception as exc:
                                    logger.debug(f"on_found callback failed for {ip}: {exc}")

                        # Refill the window
                        if not cancel_event.is_set():
                            next_ip = next(host_gen, None)
                            if next_ip is not None:
                                next_fut = executor.submit(_probe_host, next_ip, ports, timeout_sec)
                                in_flight[next_fut] = next_ip

            if progress.status == "running":
                progress.status = "done"

        except Exception as exc:
            progress.status = "error"
            progress.error = str(exc)
            logger.error(f"Range scan {job_id} failed: {exc}", exc_info=True)
        finally:
            progress.finished_at = datetime.utcnow().isoformat()

    def get_progress(self, job_id: str) -> Optional[ScanProgress]:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            flag = self._cancel_flags.get(job_id)
        if flag:
            flag.set()
            return True
        return False

    def list_jobs(self) -> List[ScanProgress]:
        with self._lock:
            return list(self._jobs.values())


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════════

_scanner_instance: Optional[RangeScanner] = None
_scanner_lock = threading.Lock()


def get_range_scanner() -> RangeScanner:
    global _scanner_instance
    with _scanner_lock:
        if _scanner_instance is None:
            _scanner_instance = RangeScanner()
        return _scanner_instance
