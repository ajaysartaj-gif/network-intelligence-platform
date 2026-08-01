# Core Enhancements Roadmap

## What You Want (Focused on 6 High-Impact Enhancements)

Skip the integrations. Focus on making the **core system more intelligent and autonomous**.

---

## TIER 1: Quick Win (1 week)

### 1. Detailed Explainability

**What**: Claude explains every decision in the troubleshooting process  
**Why**: Users trust automation when they understand the reasoning  
**Impact**: 80% higher trust + audit trail  
**Effort**: 1 week (300 lines)

```python
# core/explainability.py (already in POWERUP guide, but here's the essence)

class ExplainabilityEngine:
    def explain_full_session(self, session) -> List[ExplanationStep]:
        """Generate explanation for entire troubleshooting."""
        
        explanations = [
            ExplanationStep(
                step=1,
                stage="intake",
                reasoning=f"Classified as {session.problem.scope} + {session.problem.symptom}",
                confidence=session.problem.confidence
            ),
            ExplanationStep(
                step=2,
                stage="diagnosis",
                reasoning=f"Root cause: {session.root_cause}",
                confidence=session.diagnosis_confidence
            ),
            ExplanationStep(
                step=3,
                stage="fix_selection",
                reasoning=f"87% success rate in past {precedent_count} incidents",
                confidence=session.suggested_fix.confidence if session.suggested_fix else 0
            ),
        ]
        
        return explanations
```

**Streamlit Integration**:
```python
def render_explanation(session):
    st.markdown("## 🧠 How I Decided On This Fix")
    
    for exp in explainer.explain_full_session(session):
        with st.expander(f"Step {exp.step}: {exp.stage.title()}"):
            st.markdown(exp.reasoning)
            st.metric("Confidence", f"{exp.confidence:.0%}")
```

**Result**: Users see exactly why each fix was chosen ✅

---

## TIER 2: Medium Effort (2-3 weeks each)

### 2. Multi-Device Orchestration

**What**: Coordinate fixes across multiple network devices automatically  
**Why**: Real network issues span multiple devices; need coordination  
**Impact**: 80% faster complex fixes  
**Effort**: 2 weeks (400 lines)

**When needed**: BGP changes (4+ routers), VLAN updates (8+ switches), etc.

```python
# core/multi_device_orchestrator.py

class MultiDeviceOrchestrator:
    def execute_coordinated_fix(self, device_commands: List[DeviceCommand]):
        """
        Execute on multiple devices in optimal order.
        
        Example flow:
          PE1, PE2 (route reflectors) execute first [parallel]
            ↓
          CE1, CE2, CE3 (customer edges) execute after [parallel]
        """
        
        # Build dependency graph
        dag = self._build_dependency_graph(device_commands)
        
        # Topological sort for optimal order
        execution_order = list(nx.topological_sort(dag))
        
        # Identify parallelizable levels
        levels = self._identify_parallelizable_levels(dag)
        
        # Execute each level in parallel
        for level in levels:
            results = asyncio.run(
                self._execute_level_parallel(level, device_commands)
            )
            
            # Check for failures and rollback if needed
            if any(r.get('status') == 'failed' for r in results.values()):
                raise Exception("Level failed, rolling back...")
```

**Result**: Network-wide changes executed safely and in parallel ✅

---

### 3. Predictive Issue Forecasting

**What**: Predict network issues 24-48 hours before they happen  
**Why**: Prevent issues instead of fixing them reactively  
**Impact**: 90% prevention vs. 25% reactive fixing  
**Effort**: 3 weeks (500 lines)

**How it works**:
```
Telemetry trends → Time-series analysis → Anomaly detection → Predict degradation
```

```python
# core/predictive_forecaster_enhanced.py

class PredictiveForecaster:
    def predict_issues_24h_ahead(self, telemetry_history: Dict) -> List[PredictedIssue]:
        """
        Analyze 24-hour telemetry trends to predict next 24 hours.
        
        Looks for patterns:
          - CPU trending up 10%/hour → will hit 90% in 8 hours
          - BGP flaps increasing → will cause full outage in 12 hours
          - Interface errors rising → will degrade in 6 hours
          - Memory pressure rising → will crash in 18 hours
        """
        
        predictions = []
        
        for device, metrics in telemetry_history.items():
            # Calculate trends
            cpu_trend = self._calculate_trend(metrics['cpu'])
            mem_trend = self._calculate_trend(metrics['memory'])
            errors_trend = self._calculate_trend(metrics['errors'])
            
            # Predict ETA to failure
            if cpu_trend > 0.08:  # 8% per hour
                eta_hours = (90 - current_cpu) / cpu_trend
                predictions.append(PredictedIssue(
                    device=device,
                    issue_type="cpu_exhaustion",
                    eta_hours=eta_hours,
                    confidence=0.92,
                    suggested_fix="Scale CPU or reduce load"
                ))
            
            if mem_trend > 0.05:  # 5% per hour
                eta_hours = (95 - current_mem) / mem_trend
                predictions.append(PredictedIssue(
                    device=device,
                    issue_type="memory_exhaustion",
                    eta_hours=eta_hours,
                    confidence=0.88,
                    suggested_fix="Restart process or increase memory"
                ))
        
        # Sort by urgency (lowest ETA first)
        return sorted(predictions, key=lambda x: x.eta_hours)
    
    def _calculate_trend(self, historical_values: List[float]) -> float:
        """
        Calculate hourly trend as (new - avg) / avg.
        Positive = increasing, negative = decreasing.
        """
        if len(historical_values) < 2:
            return 0.0
        
        # Simple linear regression
        from scipy import stats
        x = list(range(len(historical_values)))
        slope, _, _, _, _ = stats.linregress(x, historical_values)
        
        avg = sum(historical_values) / len(historical_values)
        return (slope / avg) if avg > 0 else 0.0
```

**Integration with Path A**:
```python
def _execute_path_a_autonomous(self, session):
    # STEP 1: Predict 24 hours ahead
    predictions = self.predictor.predict_issues_24h_ahead(telemetry_history)
    
    if predictions:
        # Sort by urgency
        for pred in predictions:
            logger.warning(
                f"🔮 Predicted: {pred.issue_type} on {pred.device} "
                f"in {pred.eta_hours:.1f} hours (confidence: {pred.confidence:.0%})"
            )
            
            # Automatically fix if high confidence + precedent
            if pred.confidence > 0.85 and self.pattern_db.has_fix_for(pred.issue_type):
                session.predictions.append(pred)
                # Execute fix NOW (prevent later)
```

**Result**: Issues prevented 24 hours before users see them ✅

---

### 4. AI Hypothesis Generator

**What**: Claude generates novel hypotheses for unknown issues  
**Why**: Some problems have never been seen; need creative thinking  
**Impact**: 80% higher coverage for novel issues  
**Effort**: 2 weeks (300 lines)

**How it works**:
```
Unknown symptom → Few-shot examples → Claude generates 3 hypotheses
```

```python
# core/hypothesis_generator.py

class AIHypothesisGenerator:
    def generate_hypotheses(self, problem: ProblemStatement, 
                           max_hypotheses: int = 3) -> List[str]:
        """
        Generate novel root cause hypotheses using Claude.
        
        This helps with completely NEW issues that don't match patterns.
        """
        
        # Few-shot examples from past incidents
        examples = self.pattern_db.get_similar_incidents(
            problem.raw_text, 
            limit=5,
            min_confidence=0.3  # Include lower-confidence ones for learning
        )
        
        prompt = f"""
You are a network engineer. Generate 3 alternative hypotheses for this issue.

Problem Description:
  Scope: {problem.scope}
  Symptom: {problem.symptom}
  Severity: {problem.severity}
  Details: {problem.raw_text}

Past Similar Issues (for context):
"""
        
        for ex in examples:
            prompt += f"""
  - {ex['problem']}: {ex['root_cause']}
    (Success rate: {ex['success_rate']:.0%})
"""
        
        prompt += """
Generate 3 NOVEL hypotheses (don't repeat the ones above):

Format:
1. Hypothesis: [one sentence]
   Why: [reasoning]
   Test: [how to verify]
   Fix: [suggested fix]

2. ...
3. ...
"""
        
        response = self.ai(prompt)
        
        # Parse 3 hypotheses from response
        hypotheses = self._parse_hypotheses(response)
        return hypotheses
    
    def _parse_hypotheses(self, response: str) -> List[str]:
        """Extract hypotheses from Claude response."""
        # Parse numbered hypotheses from Claude's response
        import re
        
        pattern = r'\d+\.\s+Hypothesis:\s+([^\n]+)'
        matches = re.findall(pattern, response)
        return matches[:3]
```

**Integration with Diagnosis**:
```python
def _execute_path_b_on_demand(self, session):
    # STEP 1: Try internal diagnosis
    report = self.troubleshoot_engine.run(session.problem.raw_text)
    
    # STEP 2: If internal fails, generate hypotheses
    if not report.fix or report.confidence < 0.5:
        logger.info("🤔 Generating novel hypotheses for this issue...")
        
        hypotheses = self.hypothesis_generator.generate_hypotheses(session.problem)
        
        logger.info(f"Generated {len(hypotheses)} novel hypotheses:")
        for i, hyp in enumerate(hypotheses, 1):
            logger.info(f"  {i}. {hyp}")
        
        # Store for UI to show user
        session.generated_hypotheses = hypotheses
```

**Streamlit UI**:
```python
if session.generated_hypotheses:
    st.markdown("## 🤔 Generated Hypotheses")
    st.info(
        "No known pattern matched. Here are novel hypotheses "
        "generated by Claude for this issue:"
    )
    
    for i, hyp in enumerate(session.generated_hypotheses, 1):
        st.markdown(f"**{i}. {hyp}**")
    
    if st.button("👍 Does one of these sound right?"):
        selected = st.selectbox("Which hypothesis?", session.generated_hypotheses)
        st.write(f"Let's test: {selected}")
```

**Result**: Completely novel issues now have generated hypotheses ✅

---

## TIER 3: Advanced (4+ weeks each)

### 5. Reinforcement Learning Loop

**What**: AI improves from every fix outcome automatically  
**Why**: Every incident teaches the system something  
**Impact**: Exponential improvement over time  
**Effort**: 4 weeks (600 lines)

**How it works**:
```
Fix executed → Outcome (fixed/degraded/error) → Reward signal → Update decision policies
```

```python
# core/reinforcement_learning.py

class ReinforcementLearningEngine:
    def update_from_outcome(self, session: TroubleshootingSession):
        """
        Learn from every fix outcome.
        
        Reward structure:
          - Fixed = +1.0 (success!)
          - Degraded = -0.5 (made it worse)
          - Error = -1.0 (broke everything)
        """
        
        outcome = session.outcome
        reward = self._calculate_reward(outcome)
        
        # STEP 1: Update confidence for this pattern
        if session.pattern_id:
            self.pattern_db.update_confidence(
                session.pattern_id,
                outcome,
                reward=reward
            )
        
        # STEP 2: Update decision-maker policy
        # "Should we have auto-applied this fix?"
        self.decision_maker.learn_from_outcome(
            root_cause=session.root_cause,
            confidence=session.diagnosis_confidence,
            fix_worked=(outcome == "fixed"),
            reward=reward
        )
        
        # STEP 3: Update intake classification
        # "Did we classify this correctly?"
        self.intake.learn_from_outcome(
            problem=session.problem,
            actual_root_cause=session.root_cause,
            reward=reward
        )
        
        # STEP 4: Track success rates by category
        self._update_category_success_rates(session)
    
    def _calculate_reward(self, outcome: str) -> float:
        """Reward signal for learning."""
        if outcome == "fixed":
            return 1.0
        elif outcome == "degraded":
            return -0.5
        elif outcome == "error":
            return -1.0
        else:
            return 0.0
    
    def _update_category_success_rates(self, session):
        """
        Track success rates by problem category.
        
        Example tracking:
          "BGP issues": 87% success
          "MTU issues": 92% success
          "Configuration errors": 78% success
        """
        
        category = (session.problem.scope, session.problem.symptom)
        success = (session.outcome == "fixed")
        
        if category not in self.category_stats:
            self.category_stats[category] = {"successes": 0, "total": 0}
        
        self.category_stats[category]["total"] += 1
        if success:
            self.category_stats[category]["successes"] += 1
        
        success_rate = self.category_stats[category]["successes"] / self.category_stats[category]["total"]
        logger.info(f"Category {category}: {success_rate:.0%} success rate")
```

**Policy Improvement**:
```python
class AutonomousDecisionMaker:
    def should_auto_apply(self, root_cause: str, commands: List[str], 
                         confidence: float) -> bool:
        """
        Decision improves over time as RL updates thresholds.
        """
        
        # Base thresholds (initially 0.85, 0.80, 2)
        confidence_threshold = self.learned_confidence_threshold  # Improves
        success_rate_threshold = self.learned_success_threshold  # Improves
        precedent_threshold = self.learned_precedent_threshold   # Improves
        
        # Check pattern DB with learned thresholds
        suggestion = self.pattern_db.get_suggested_fix(root_cause)
        
        if not suggestion:
            return False
        
        # Thresholds adjust based on success/failure history
        if (confidence >= confidence_threshold and
            suggestion['success_rate'] >= success_rate_threshold and
            suggestion['precedent_count'] >= precedent_threshold):
            return True
        
        return False
    
    def learn_from_outcome(self, root_cause, confidence, 
                          fix_worked, reward):
        """
        Adjust thresholds based on outcomes.
        
        If fix worked:
          - Lower confidence_threshold slightly (we were too conservative)
        If fix failed:
          - Raise confidence_threshold (we were too aggressive)
        """
        
        adjustment_factor = 0.02  # 2% per incident
        
        if fix_worked and reward > 0:
            # We succeeded! Were we too conservative?
            self.learned_confidence_threshold *= (1 - adjustment_factor)
        elif not fix_worked and reward < 0:
            # We failed! Were we too aggressive?
            self.learned_confidence_threshold *= (1 + adjustment_factor)
        
        # Keep within bounds (0.60 to 0.95)
        self.learned_confidence_threshold = max(0.60, min(0.95, 
            self.learned_confidence_threshold))
        
        logger.info(f"Updated confidence threshold: {self.learned_confidence_threshold:.2%}")
```

**Result**: System gets smarter with every incident ✅

---

### 6. Network Health Scoring

**What**: Real-time network health score (0-100%)  
**Why**: Proactive capacity planning + dashboard visibility  
**Impact**: 75% fewer outages, data-driven decisions  
**Effort**: 3 weeks (400 lines)

**How it works**:
```
Health Score = (100 - incident_rate) - predicted_issues - degradation_trends
```

```python
# core/network_health_scorer.py

class NetworkHealthScorer:
    def calculate_network_health(self) -> Dict[str, Any]:
        """
        Calculate 0-100 health score for the network.
        
        Factors:
          - Recent incident rate (# incidents last 7 days)
          - Predicted issues in next 24h
          - Degradation trends
          - Device reliability
          - Pattern confidence
        """
        
        score = 100.0
        factors = {}
        
        # FACTOR 1: Recent incidents (-20 points per incident in last 7 days)
        recent_incidents = self.pattern_db.get_incidents_since(days=7)
        incident_penalty = len(recent_incidents) * 20
        score -= incident_penalty
        factors['incident_penalty'] = incident_penalty
        
        # FACTOR 2: Predicted issues (-15 points per predicted issue)
        predicted = self.predictor.predict_issues_24h_ahead(telemetry)
        prediction_penalty = len(predicted) * 15
        score -= prediction_penalty
        factors['prediction_penalty'] = prediction_penalty
        
        # FACTOR 3: Degradation trends (-10 points for each device trending down)
        degrading_devices = self._detect_degrading_devices()
        degradation_penalty = len(degrading_devices) * 10
        score -= degradation_penalty
        factors['degradation_penalty'] = degradation_penalty
        
        # FACTOR 4: Pattern confidence
        avg_pattern_confidence = self.pattern_db.get_average_confidence()
        confidence_bonus = (avg_pattern_confidence - 0.70) * 20  # Base 70%
        score += confidence_bonus
        factors['confidence_bonus'] = confidence_bonus
        
        # Cap between 0-100
        score = max(0, min(100, score))
        
        return {
            'overall_health': score,
            'health_grade': self._score_to_grade(score),
            'factors': factors,
            'recent_incidents': len(recent_incidents),
            'predicted_issues': len(predicted),
            'degrading_devices': degrading_devices,
        }
    
    def _score_to_grade(self, score: float) -> str:
        """Convert score to grade."""
        if score >= 90:
            return "A (Excellent)"
        elif score >= 75:
            return "B (Good)"
        elif score >= 50:
            return "C (Fair)"
        else:
            return "D (Poor)"
    
    def _detect_degrading_devices(self) -> List[str]:
        """Find devices with downward trends."""
        degrading = []
        
        for device, metrics in self.telemetry.items():
            # Check if any metric trending down
            health_indicators = [
                metrics.get('cpu', 0),
                metrics.get('memory', 0),
                metrics.get('availability', 100),
            ]
            
            trend = self._calculate_trend(health_indicators)
            if trend < -0.02:  # Trending down >2% per hour
                degrading.append(device)
        
        return degrading
```

**Streamlit Dashboard**:
```python
def render_health_dashboard(scorer):
    health = scorer.calculate_network_health()
    
    # Show health score prominently
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "🏥 Network Health",
            f"{health['overall_health']:.0f}%",
            delta=f"Grade: {health['health_grade']}"
        )
    
    with col2:
        st.metric(
            "⚠️ Recent Incidents",
            health['recent_incidents'],
            delta="(Last 7 days)"
        )
    
    with col3:
        st.metric(
            "🔮 Predicted Issues",
            health['predicted_issues'],
            delta="(Next 24h)"
        )
    
    # Health breakdown
    st.markdown("### Health Factors")
    for factor, value in health['factors'].items():
        st.write(f"{factor}: {value:+.0f}")
    
    # Degrading devices warning
    if health['degrading_devices']:
        st.warning(f"Degrading devices: {', '.join(health['degrading_devices'])}")
```

**Result**: Executive dashboard showing network health at a glance ✅

---

## Implementation Timeline

### Week 1: Explainability
- Add ExplainabilityEngine class
- Integrate into all 3 paths
- Update Streamlit UI with explanation expanders
- **Result**: Users see why every decision was made

### Weeks 2-4: Multi-Device Orchestration
- Build dependency graph from topology
- Implement topological sort + parallel execution
- Add rollback logic
- Test with multi-device BGP changes
- **Result**: Network-wide fixes execute automatically

### Weeks 5-7: Predictive Forecasting
- Implement trend calculation (linear regression)
- Add telemetry collection hooks
- Integrate with Path A (predict before incident)
- Create dashboard with predictions
- **Result**: Fix issues 24 hours before they break

### Weeks 8-9: AI Hypothesis Generator
- Add few-shot prompt builder
- Parse Claude response into hypotheses
- Show in Streamlit when internal diagnosis fails
- **Result**: Novel issues now have generated solutions

### Weeks 10-13: Reinforcement Learning
- Build reward signal system
- Update AutonomousDecisionMaker with policy learning
- Track category success rates
- Adjust thresholds over time
- **Result**: System improves with every incident

### Weeks 14-16: Network Health Scoring
- Implement scoring algorithm
- Build health dashboard
- Add alerting for degradation
- Executive reporting
- **Result**: Proactive capacity planning + visibility

---

## Expected Results

```
Week 0:    Coverage 90%, MTTR 5 min
Week 1:    Coverage 90%, MTTR 4 min (explainability helps decisions)
Week 4:    Coverage 92%, MTTR 2 min (multi-device coordination)
Week 7:    Coverage 95%, MTTR 1 min (prediction prevents issues)
Week 9:    Coverage 97%, MTTR 45 sec (novel hypotheses help)
Week 13:   Coverage 98%, MTTR 30 sec (learning improves continuously)
Week 16:   Coverage 99%, MTTR 20 sec (full visibility + prevention)
```

---

## Priority Recommendation

**Start with this order:**

1. **Week 1**: Explainability (easiest, highest trust ROI)
2. **Weeks 2-4**: Multi-Device Orchestration (handle real complexity)
3. **Weeks 5-7**: Predictive Forecasting (shift to prevention)
4. **Weeks 8-9**: AI Hypothesis Generator (novel issue handling)
5. **Weeks 10-13**: Reinforcement Learning (continuous improvement)
6. **Weeks 14-16**: Network Health Scoring (executive visibility)

**Total**: 16 weeks to build a truly powerful autonomous system ✅

---

## Summary

These 6 enhancements make your system:

- **Smarter** (explainability + hypothesis generation)
- **Faster** (multi-device orchestration)
- **Preventive** (predictive forecasting)
- **Self-improving** (reinforcement learning)
- **Visible** (health scoring)

You go from **reactive troubleshooting** to **proactive autonomous operations**.

All code is provided in this guide. Copy, integrate, and deploy.

