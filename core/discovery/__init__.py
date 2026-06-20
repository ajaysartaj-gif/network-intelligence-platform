"""
core/discovery/
================
RFC 1918-aware network range scanning.

Public API:
  - RFC1918_RANGES, parse_cidr, host_count, iter_hosts — network_ranges.py
  - get_local_subnets() — auto-detect subnets this machine is connected to
  - estimate_scan_seconds(), format_duration() — honest time estimates
  - RangeScanner, get_range_scanner() — bounded-concurrency scan engine
  - ScanProgress — live progress for the UI to poll
"""
from core.discovery.network_ranges import (
    RFC1918_RANGES,
    RangePreset,
    LocalSubnet,
    parse_cidr,
    host_count,
    iter_hosts,
    estimate_scan_seconds,
    format_duration,
    get_local_subnets,
)
from core.discovery.range_scanner import (
    RangeScanner,
    ScanProgress,
    get_range_scanner,
)

__all__ = [
    "RFC1918_RANGES",
    "RangePreset",
    "LocalSubnet",
    "parse_cidr",
    "host_count",
    "iter_hosts",
    "estimate_scan_seconds",
    "format_duration",
    "get_local_subnets",
    "RangeScanner",
    "ScanProgress",
    "get_range_scanner",
]
