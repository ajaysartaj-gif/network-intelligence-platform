"""
Network Copilot - Diagnostic Engine for Network Troubleshooting

Sprint 1: OSPF Diagnostic (Reactive Troubleshooting)

Pipeline:
  Input (CLI outputs)
    ↓
  Normalize (parse, standardize)
    ↓
  Protocol Reasoning (state machine logic)
    ↓
  Evidence Ranking (what's relevant?)
    ↓
  Hypothesis (root cause)
    ↓
  Verification (what commands prove this?)
    ↓
  Recommended Fix

Success Metric:
  A CCIE chooses this over ChatGPT for OSPF troubleshooting
  because it is faster, more accurate, and explains with evidence.
"""

__version__ = "0.1.0"
__author__ = "Network Copilot"
