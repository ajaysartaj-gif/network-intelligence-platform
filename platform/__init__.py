"""
Network Intelligence Platform

A domain-agnostic infrastructure engineering platform for:
- Network troubleshooting and diagnosis
- Infrastructure design and planning
- Configuration management and change safety
- Cross-domain dependency intelligence
"""

from .fundamentals import (
    InfrastructurePlatform,
    InfrastructureDomain,
    ProblemCategory,
    ChangeType,
    Observation,
    Theory,
    Investigation,
    ProposedChange,
    DesignOption,
    DecisionRecord,
)

from .intelligence import DependencyIntelligence

__all__ = [
    "InfrastructurePlatform",
    "InfrastructureDomain",
    "ProblemCategory",
    "ChangeType",
    "Observation",
    "Theory",
    "Investigation",
    "ProposedChange",
    "DesignOption",
    "DecisionRecord",
    "DependencyIntelligence",
]
