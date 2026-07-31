"""
core/prediction_forecaster.py
=============================
Predict network issues before they break using learned patterns.

Enables Path A (Autonomous):
- Detect patterns in current telemetry
- Match against historical failure patterns
- Forecast issues with time estimates
- Make autonomous decisions about fixes
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Prediction Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PredictedIssue:
    """A forecasted problem."""
    issue_description: str
    root_cause: str
    probability: float                # 0.0-1.0
    eta_minutes: float               # Estimated time to incident
    confidence: float                # How sure are we?
    suggested_preventive_action: Optional[str] = None
    historical_precedents: int = 0   # How many times we've seen this


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern-Based Predictor
# ═══════════════════════════════════════════════════════════════════════════════

class PatternPredictor:
    """
    Predict issues before they happen by matching current telemetry to
    historical patterns that preceded incidents.

    Example:
      Pattern learned: "When MTU changes on 3+ interfaces AND interface
                        flap rate > 0.5 per minute, latency spike follows
                        in ~5-10 minutes with 85% confidence"

      Current state: Detects MTU changes on 3 interfaces + flap rate at 0.6
                     → Triggers prediction: "Latency spike expected in 7 min"
"""

    def __init__(self, pattern_db: Any):
        """
        Parameters
        ----------
        pattern_db : PatternDatabase
            Database of learned patterns and historical incidents
        """
        self.db = pattern_db

    def predict_degradation(self,
                           topology: Any,
                           current_metrics: Dict[str, Any],
                           recent_events: Optional[List[Dict[str, Any]]] = None) -> List[PredictedIssue]:
        """
        Scan current network state for conditions that historically preceded issues.

        Parameters
        ----------
        topology : TopologyGraph
            Current network topology
        current_metrics : Dict
            Real-time device/link metrics from telemetry engine
        recent_events : List[Dict], optional
            Recent events (config changes, interface flaps, etc.)

        Returns
        -------
        List[PredictedIssue]
            Predicted issues sorted by probability (highest first)
        """
        predictions = []

        # Get all learned patterns from pattern DB
        patterns = self.db.get_failure_patterns()

        for pattern in patterns:
            # Check if current state matches this pattern's triggers
            match_score = self._pattern_matches_current_state(
                pattern, current_metrics, topology, recent_events
            )

            if match_score > 0.5:  # Threshold: >50% match = prediction
                prediction = PredictedIssue(
                    issue_description=pattern['predicted_issue'],
                    root_cause=pattern['triggers'][0] if pattern['triggers'] else "unknown",
                    probability=match_score,
                    eta_minutes=pattern['average_time_to_incident'],
                    confidence=pattern['historical_accuracy'],
                    suggested_preventive_action=pattern['preventive_fix'],
                    historical_precedents=pattern['occurrence_count'],
                )
                predictions.append(prediction)

        # Sort by probability (highest first)
        predictions.sort(reverse=True, key=lambda x: x.probability)

        if predictions:
            logger.info(f"🔮 Predicted {len(predictions)} potential issue(s)")
            for pred in predictions[:3]:
                logger.info(
                    f"  - {pred.issue_description} "
                    f"(ETA: {pred.eta_minutes:.0f}m, confidence: {pred.confidence:.0%})"
                )

        return predictions

    def _pattern_matches_current_state(self,
                                       pattern: Dict[str, Any],
                                       metrics: Dict[str, Any],
                                       topology: Any,
                                       recent_events: Optional[List[Dict]] = None) -> float:
        """
        Check if current telemetry matches this historical pattern.

        Returns match score (0.0-1.0). Score > 0.5 triggers prediction.
        """
        triggers = pattern.get('triggers', [])
        if not triggers:
            return 0.0

        match_score = 0.0
        matched_triggers = 0

        for trigger in triggers:
            if self._trigger_is_present(trigger, metrics, topology, recent_events):
                matched_triggers += 1

        if matched_triggers > 0:
            # Partial credit: score = fraction of triggers matched
            match_score = matched_triggers / len(triggers)

        return match_score

    def _trigger_is_present(self,
                           trigger: str,
                           metrics: Dict[str, Any],
                           topology: Any,
                           recent_events: Optional[List[Dict]] = None) -> bool:
        """
        Check if a specific trigger is present in current state.

        Trigger examples:
        - "mtu_change_on_3_devices"
        - "interface_flap_rate_high"
        - "cpu_spike_on_core"
        - "bgp_session_unstable"
        """
        trigger_lower = trigger.lower()

        # MTU changes
        if "mtu" in trigger_lower:
            mtu_changes = self._count_mtu_changes(metrics, topology)
            threshold = self._extract_threshold(trigger, default=2)
            return mtu_changes >= threshold

        # Interface flapping
        elif "flap" in trigger_lower or "instability" in trigger_lower:
            flap_rate = self._calculate_flap_rate(metrics)
            threshold = self._extract_threshold(trigger, default=0.5)
            return flap_rate >= threshold

        # CPU spike
        elif "cpu" in trigger_lower or "processor" in trigger_lower:
            cpu_max = self._get_max_metric(metrics, "cpu_utilization")
            threshold = self._extract_threshold(trigger, default=85.0)
            return cpu_max >= threshold

        # Memory pressure
        elif "memory" in trigger_lower or "buffer" in trigger_lower:
            mem_max = self._get_max_metric(metrics, "memory_utilization")
            threshold = self._extract_threshold(trigger, default=85.0)
            return mem_max >= threshold

        # BGP instability
        elif "bgp" in trigger_lower:
            bgp_changes = self._count_bgp_changes(metrics, recent_events)
            return bgp_changes > 2

        # Packet loss
        elif "loss" in trigger_lower or "drop" in trigger_lower:
            max_loss = self._get_max_metric(metrics, "packet_loss_percent")
            threshold = self._extract_threshold(trigger, default=1.0)
            return max_loss >= threshold

        # Latency increase
        elif "latency" in trigger_lower or "rtt" in trigger_lower:
            max_latency = self._get_max_metric(metrics, "latency_ms")
            threshold = self._extract_threshold(trigger, default=100.0)
            return max_latency >= threshold

        return False

    # ── Trigger detection helpers ──────────────────────────────────────────────

    @staticmethod
    def _count_mtu_changes(metrics: Dict[str, Any], topology: Any) -> int:
        """Count devices where MTU changed recently."""
        count = 0
        if "mtu_changes" in metrics:
            count = len(metrics.get("mtu_changes", []))
        return count

    @staticmethod
    def _calculate_flap_rate(metrics: Dict[str, Any]) -> float:
        """Calculate interface flap rate (flaps per minute)."""
        total_flaps = metrics.get("total_interface_flaps", 0)
        time_window_minutes = metrics.get("observation_window_minutes", 1)

        if time_window_minutes <= 0:
            return 0.0

        return total_flaps / time_window_minutes

    @staticmethod
    def _count_bgp_changes(metrics: Dict[str, Any],
                          recent_events: Optional[List[Dict]] = None) -> int:
        """Count BGP session state changes."""
        count = metrics.get("bgp_session_changes", 0)

        if recent_events:
            count += sum(1 for evt in recent_events
                        if "bgp" in evt.get("type", "").lower())

        return count

    @staticmethod
    def _get_max_metric(metrics: Dict[str, Any], metric_name: str, default: float = 0.0) -> float:
        """Get maximum value of a metric across all devices."""
        if metric_name not in metrics:
            return default

        values = metrics[metric_name]
        if isinstance(values, dict):
            return max(values.values()) if values else default
        elif isinstance(values, list):
            return max(values) if values else default
        else:
            return float(values) if values else default

    @staticmethod
    def _extract_threshold(trigger: str, default: float = 50.0) -> float:
        """Extract numeric threshold from trigger string."""
        # e.g., "cpu_spike_on_core_80" → 80.0
        words = trigger.split("_")
        for word in reversed(words):
            try:
                return float(word)
            except ValueError:
                continue
        return default


# ═══════════════════════════════════════════════════════════════════════════════
# Autonomous Decision Maker
# ═══════════════════════════════════════════════════════════════════════════════

class AutonomousDecisionMaker:
    """
    Decide whether to automatically apply a fix or queue for approval.

    Uses pattern history: if this exact fix worked >80% of the time in
    similar situations, and root cause confidence is high, apply it
    automatically. Otherwise, queue for human approval.

    This gate keeps Path A safe while still providing autonomous benefits.
    """

    def __init__(self,
                 pattern_db: Any,
                 confidence_threshold: float = 0.85,
                 success_rate_threshold: float = 0.80):
        """
        Parameters
        ----------
        pattern_db : PatternDatabase
        confidence_threshold : float
            Min confidence to auto-apply (0.0-1.0)
        success_rate_threshold : float
            Min success rate of this fix in past (0.0-1.0)
        """
        self.db = pattern_db
        self.confidence_threshold = confidence_threshold
        self.success_rate_threshold = success_rate_threshold

    def should_auto_apply(self,
                         root_cause: str,
                         suggested_fix: str,
                         confidence: float) -> bool:
        """
        Decide whether to automatically apply a fix.

        Parameters
        ----------
        root_cause : str
            Diagnosed root cause
        suggested_fix : str
            The fix command(s)
        confidence : float
            Confidence in diagnosis (0.0-1.0)

        Returns
        -------
        bool
            True if confidence is high enough + fix has good track record
        """

        # Check 1: Is diagnosis confidence high enough?
        if confidence < self.confidence_threshold:
            logger.info(
                f"Not auto-applying: diagnosis confidence {confidence:.0%} "
                f"< threshold {self.confidence_threshold:.0%}"
            )
            return False

        # Check 2: Has this exact fix worked before?
        suggestion = self.db.get_suggested_fix(root_cause)

        if not suggestion:
            logger.info(f"Not auto-applying: fix not in pattern DB (new diagnosis)")
            return False

        success_rate = suggestion.get("success_rate", 0.0)
        precedent_count = suggestion.get("precedent_count", 0)

        if precedent_count < 2:  # Need at least 2 precedents
            logger.info(f"Not auto-applying: only {precedent_count} precedent(s)")
            return False

        if success_rate < self.success_rate_threshold:
            logger.info(
                f"Not auto-applying: fix success rate {success_rate:.0%} "
                f"< threshold {self.success_rate_threshold:.0%}"
            )
            return False

        # All gates passed
        logger.info(
            f"✅ Auto-applying fix: confidence={confidence:.0%}, "
            f"success_rate={success_rate:.0%}, precedents={precedent_count}"
        )
        return True

    def get_approval_recommendation(self,
                                   root_cause: str,
                                   suggested_fix: str,
                                   confidence: float) -> Dict[str, Any]:
        """
        Generate a recommendation message for human approval.

        Returns dict with:
        - recommended_action: "auto_apply" | "approve" | "investigate"
        - message: Human-readable explanation
        - risk_level: "low" | "medium" | "high"
        """
        auto_apply = self.should_auto_apply(root_cause, suggested_fix, confidence)

        if auto_apply:
            return {
                "recommended_action": "auto_apply",
                "message": "✅ This fix worked in similar situations 80%+ of the time. Auto-applying.",
                "risk_level": "low",
            }

        suggestion = self.db.get_suggested_fix(root_cause)

        if suggestion:
            success_rate = suggestion.get("success_rate", 0.0)
            precedents = suggestion.get("precedent_count", 0)

            return {
                "recommended_action": "approve",
                "message": (
                    f"🔧 Suggested fix (success rate: {success_rate:.0%} in {precedents} past incidents). "
                    f"Diagnosis confidence: {confidence:.0%}. Awaiting approval."
                ),
                "risk_level": "medium",
            }
        else:
            return {
                "recommended_action": "investigate",
                "message": (
                    f"⚠️ New diagnosis pattern. Investigate before applying fix. "
                    f"Confidence: {confidence:.0%}"
                ),
                "risk_level": "high",
            }
