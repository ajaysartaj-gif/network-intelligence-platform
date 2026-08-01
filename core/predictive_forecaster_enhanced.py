"""
core/predictive_forecaster_enhanced.py
======================================
Predict network issues 24-48 hours before they happen.

Analyzes telemetry trends to forecast degradation and enable prevention.
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PredictedIssue:
    """A predicted network issue."""
    device: str
    issue_type: str  # "cpu_exhaustion", "memory_exhaustion", "bgp_flap", "packet_loss", etc.
    eta_hours: float  # How many hours until issue manifests
    confidence: float  # 0.0-1.0 confidence in this prediction
    current_value: float  # Current metric value
    threshold_value: float  # Value that triggers the issue
    trend_rate: float  # Rate of change per hour (0.05 = 5% per hour)
    suggested_fix: Optional[str] = None
    urgency: str = "medium"  # "low" | "medium" | "high" | "critical"


class PredictiveForecaster:
    """Predict network issues before they impact users."""

    def __init__(self, pattern_db: Optional[Any] = None):
        """
        Parameters
        ----------
        pattern_db : PatternDatabase, optional
            Database of past incidents for context
        """
        self.pattern_db = pattern_db
        self.telemetry_history = {}
        logger.info("PredictiveForecaster initialized")

    def predict_issues_24h_ahead(self,
                                telemetry_history: Dict[str, Dict[str, List[float]]]) -> List[PredictedIssue]:
        """
        Analyze 24-hour telemetry trends to predict next 24 hours.

        Looks for patterns:
        - CPU trending up 10%/hour → will hit 90% in 8 hours
        - BGP flaps increasing → will cause outage in 12 hours
        - Interface errors rising → will degrade in 6 hours
        - Memory pressure rising → will crash in 18 hours

        Parameters
        ----------
        telemetry_history : Dict[str, Dict[str, List[float]]]
            Historical telemetry data
            Format: {device: {metric_name: [values]}}

        Returns
        -------
        List[PredictedIssue]
            Predicted issues sorted by urgency (lowest ETA first)
        """
        predictions = []
        self.telemetry_history = telemetry_history

        logger.info(f"Analyzing telemetry for {len(telemetry_history)} device(s)")

        for device, metrics in telemetry_history.items():
            # Analyze CPU
            if "cpu" in metrics:
                cpu_prediction = self._predict_cpu_exhaustion(device, metrics["cpu"])
                if cpu_prediction:
                    predictions.append(cpu_prediction)

            # Analyze Memory
            if "memory" in metrics:
                mem_prediction = self._predict_memory_exhaustion(device, metrics["memory"])
                if mem_prediction:
                    predictions.append(mem_prediction)

            # Analyze Interface Errors
            if "interface_errors" in metrics:
                error_prediction = self._predict_interface_degradation(device, metrics["interface_errors"])
                if error_prediction:
                    predictions.append(error_prediction)

            # Analyze BGP Flaps
            if "bgp_flaps" in metrics:
                bgp_prediction = self._predict_bgp_instability(device, metrics["bgp_flaps"])
                if bgp_prediction:
                    predictions.append(bgp_prediction)

            # Analyze Packet Loss
            if "packet_loss" in metrics:
                loss_prediction = self._predict_packet_loss_rise(device, metrics["packet_loss"])
                if loss_prediction:
                    predictions.append(loss_prediction)

            # Analyze Latency
            if "latency_ms" in metrics:
                latency_prediction = self._predict_latency_spike(device, metrics["latency_ms"])
                if latency_prediction:
                    predictions.append(latency_prediction)

        # Sort by urgency (lowest ETA first)
        predictions.sort(key=lambda x: x.eta_hours)

        logger.info(f"Predicted {len(predictions)} potential issue(s)")
        for pred in predictions:
            logger.warning(
                f"  🔮 {pred.device}: {pred.issue_type} "
                f"in {pred.eta_hours:.1f}h (confidence: {pred.confidence:.0%})"
            )

        return predictions

    def _predict_cpu_exhaustion(self, device: str, cpu_history: List[float]) -> Optional[PredictedIssue]:
        """Predict CPU exhaustion based on trend."""
        if len(cpu_history) < 2:
            return None

        current_cpu = cpu_history[-1]
        threshold = 90.0
        warning_threshold = 75.0

        # Calculate trend
        trend_rate = self._calculate_trend(cpu_history)  # % per hour

        if trend_rate <= 0.01:  # Not trending up
            return None

        if current_cpu < warning_threshold:
            # Estimate hours until threshold
            eta_hours = (threshold - current_cpu) / trend_rate

            if eta_hours < 24:  # Only predict if within 24 hours
                return PredictedIssue(
                    device=device,
                    issue_type="cpu_exhaustion",
                    eta_hours=eta_hours,
                    confidence=self._calculate_trend_confidence(cpu_history),
                    current_value=current_cpu,
                    threshold_value=threshold,
                    trend_rate=trend_rate,
                    suggested_fix="Scale CPU, reduce load, or optimize processes",
                    urgency="high" if eta_hours < 6 else "medium"
                )

        return None

    def _predict_memory_exhaustion(self, device: str, memory_history: List[float]) -> Optional[PredictedIssue]:
        """Predict memory exhaustion based on trend."""
        if len(memory_history) < 2:
            return None

        current_mem = memory_history[-1]
        threshold = 95.0
        warning_threshold = 80.0

        trend_rate = self._calculate_trend(memory_history)  # % per hour

        if trend_rate <= 0.005:  # Not trending up
            return None

        if current_mem < warning_threshold:
            eta_hours = (threshold - current_mem) / trend_rate

            if eta_hours < 24:
                return PredictedIssue(
                    device=device,
                    issue_type="memory_exhaustion",
                    eta_hours=eta_hours,
                    confidence=self._calculate_trend_confidence(memory_history),
                    current_value=current_mem,
                    threshold_value=threshold,
                    trend_rate=trend_rate,
                    suggested_fix="Restart service, increase memory, or add more capacity",
                    urgency="critical" if eta_hours < 4 else "high"
                )

        return None

    def _predict_interface_degradation(self, device: str, error_history: List[float]) -> Optional[PredictedIssue]:
        """Predict interface degradation based on error trends."""
        if len(error_history) < 3:
            return None

        current_errors = error_history[-1]
        baseline_errors = np.mean(error_history[:-5]) if len(error_history) > 5 else error_history[0]

        # If errors increasing rapidly
        trend_rate = self._calculate_trend(error_history)

        if trend_rate > 0.1:  # Errors rising >10% per hour
            eta_hours = 12.0  # Issues manifest in ~12 hours

            return PredictedIssue(
                device=device,
                issue_type="interface_degradation",
                eta_hours=eta_hours,
                confidence=0.75,
                current_value=current_errors,
                threshold_value=current_errors * 2,  # Double baseline
                trend_rate=trend_rate,
                suggested_fix="Check interface health, optical signal, or cable quality",
                urgency="high"
            )

        return None

    def _predict_bgp_instability(self, device: str, flap_history: List[float]) -> Optional[PredictedIssue]:
        """Predict BGP instability based on flap frequency."""
        if len(flap_history) < 3:
            return None

        current_flaps = flap_history[-1]
        trend_rate = self._calculate_trend(flap_history)

        # If flaps are increasing
        if trend_rate > 0.05 or current_flaps > 5:
            eta_hours = 6.0  # BGP issues escalate quickly

            return PredictedIssue(
                device=device,
                issue_type="bgp_instability",
                eta_hours=eta_hours,
                confidence=0.80,
                current_value=current_flaps,
                threshold_value=20.0,  # Threshold for outage
                trend_rate=trend_rate,
                suggested_fix="Clear BGP session, check MTU, verify peering config",
                urgency="critical"
            )

        return None

    def _predict_packet_loss_rise(self, device: str, loss_history: List[float]) -> Optional[PredictedIssue]:
        """Predict packet loss increase based on trend."""
        if len(loss_history) < 2:
            return None

        current_loss = loss_history[-1]
        threshold = 1.0  # 1% loss is significant

        trend_rate = self._calculate_trend(loss_history)

        if trend_rate > 0.02 and current_loss < threshold:
            eta_hours = (threshold - current_loss) / trend_rate

            if eta_hours < 24:
                return PredictedIssue(
                    device=device,
                    issue_type="packet_loss_rise",
                    eta_hours=eta_hours,
                    confidence=0.70,
                    current_value=current_loss,
                    threshold_value=threshold,
                    trend_rate=trend_rate,
                    suggested_fix="Check network congestion, QoS settings, or hardware issues",
                    urgency="high" if eta_hours < 6 else "medium"
                )

        return None

    def _predict_latency_spike(self, device: str, latency_history: List[float]) -> Optional[PredictedIssue]:
        """Predict latency increase based on trend."""
        if len(latency_history) < 3:
            return None

        current_latency = latency_history[-1]
        baseline_latency = np.mean(latency_history[:-5]) if len(latency_history) > 5 else latency_history[0]
        threshold = baseline_latency * 1.5  # 50% increase is significant

        trend_rate = self._calculate_trend(latency_history)

        if trend_rate > 0.1 and current_latency < threshold:
            eta_hours = (threshold - current_latency) / trend_rate

            if eta_hours < 24:
                return PredictedIssue(
                    device=device,
                    issue_type="latency_spike",
                    eta_hours=eta_hours,
                    confidence=0.65,
                    current_value=current_latency,
                    threshold_value=threshold,
                    trend_rate=trend_rate,
                    suggested_fix="Check network congestion, routing, or optical signal",
                    urgency="medium"
                )

        return None

    def _calculate_trend(self, values: List[float]) -> float:
        """
        Calculate hourly trend using linear regression.

        Returns: Rate of change as % per hour
        Example: 0.05 = 5% per hour increase
        """
        if len(values) < 2:
            return 0.0

        # Simple linear regression
        try:
            x = np.arange(len(values))
            y = np.array(values, dtype=float)

            # Calculate slope
            slope = np.polyfit(x, y, 1)[0]

            # Normalize to percentage per hour
            avg_value = np.mean(y)
            if avg_value <= 0:
                return 0.0

            trend = (slope / avg_value) if avg_value > 0 else 0.0
            return max(-1.0, min(1.0, trend))  # Clamp to [-1.0, 1.0]

        except Exception as e:
            logger.warning(f"Trend calculation failed: {e}")
            return 0.0

    def _calculate_trend_confidence(self, values: List[float]) -> float:
        """Calculate confidence in the trend based on variance and length."""
        if len(values) < 3:
            return 0.3

        # More data = higher confidence
        data_confidence = min(0.9, len(values) / 20)

        # Low variance = higher confidence (consistent trend)
        variance = np.var(values[-5:]) if len(values) >= 5 else np.var(values)
        avg = np.mean(values)

        if avg == 0:
            variance_confidence = 0.3
        else:
            cv = variance / (avg ** 2)  # Coefficient of variation
            variance_confidence = max(0.2, 1.0 - cv)

        # Combine
        confidence = (data_confidence + variance_confidence) / 2
        return max(0.3, min(0.95, confidence))

    def print_predictions(self, predictions: List[PredictedIssue]) -> str:
        """Generate human-readable prediction report."""
        if not predictions:
            return "✅ No issues predicted for the next 24 hours\n"

        report = "🔮 NETWORK PREDICTIONS (Next 24 Hours)\n"
        report += "=" * 60 + "\n\n"

        # Group by urgency
        urgent = [p for p in predictions if p.urgency in ["critical", "high"]]
        medium = [p for p in predictions if p.urgency == "medium"]
        low = [p for p in predictions if p.urgency == "low"]

        if urgent:
            report += "🚨 CRITICAL/HIGH URGENCY:\n"
            for pred in urgent:
                report += f"  • {pred.device}: {pred.issue_type}\n"
                report += f"    ETA: {pred.eta_hours:.1f} hours\n"
                report += f"    Current: {pred.current_value:.1f}% → Threshold: {pred.threshold_value:.1f}%\n"
                report += f"    Confidence: {pred.confidence:.0%}\n"
                report += f"    Fix: {pred.suggested_fix}\n\n"

        if medium:
            report += "\n⚠️  MEDIUM URGENCY:\n"
            for pred in medium:
                report += f"  • {pred.device}: {pred.issue_type} ({pred.eta_hours:.1f}h)\n"

        if low:
            report += "\n📋 LOW URGENCY:\n"
            for pred in low:
                report += f"  • {pred.device}: {pred.issue_type} ({pred.eta_hours:.1f}h)\n"

        report += "\n" + "=" * 60
        report += f"\nTotal: {len(predictions)} issue(s) predicted\n"

        return report
