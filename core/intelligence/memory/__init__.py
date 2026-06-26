"""
core/intelligence/memory
=========================
Derived, consolidating memory — the layer that lets the platform stop being a
fast amnesiac and gradually become an experienced network engineer.

The episodic log (core/intelligence/operational_memory.py) remembers events.
This package consolidates those events into the kinds of memory an expert
actually reasons from:

  Semantic · Procedural · Pattern · Failure · Experience · Temporal ·
  Environmental · Topology-Evolution · Operator-Preference · Trust ·
  Prediction · Decision · Verification · Business/Customer · Episodic-Recall

One facade ties them together:

  from core.intelligence.memory import get_memory_system, wire_memory_system
  wire_memory_system()                  # at startup
  sysm = get_memory_system()
  sysm.record_from_contract(contract)   # write path (after a verified change)
  ctx = sysm.recall(intent=..., symptoms=..., protocol=..., device=...)  # read
"""
from core.intelligence.memory.memory_system import (
    MemorySystem, get_memory_system, wire_memory_system,
)

__all__ = ["MemorySystem", "get_memory_system", "wire_memory_system"]
