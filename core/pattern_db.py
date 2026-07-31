"""
core/pattern_db.py
===================
Persistent storage and query engine for incident patterns.

Enables:
- Recording resolved incidents (problem → root cause → fix → outcome)
- Similarity search: "Have we seen this problem before?"
- Confidence updates: "That fix worked, increase its confidence"
- Pattern-based prediction: "When MTU changes, latency spikes"

This is the learning foundation for Path C and data source for Path A forecasting.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    logger.warning("sentence-transformers not installed — similarity search disabled")


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class IncidentPattern:
    """One historical incident and its resolution."""
    id: str                              # UUID
    problem_description: str             # "Network slow between NYC and SF"
    root_cause: str                      # "MTU mismatch on WAN link"
    fix_applied: str                     # "Set interface MTU 1500"
    outcome: str                         # "fixed" | "degraded" | "no_change"
    time_to_resolution_minutes: float    # How long to diagnose + fix?
    operator_feedback: Optional[str] = None
    confidence: float = 0.5              # Updated based on feedback (0.0-1.0)
    recorded_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    embedding: Optional[List[float]] = None  # For semantic search


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern Database
# ═══════════════════════════════════════════════════════════════════════════════

class PatternDatabase:
    """
    Persistent incident pattern storage with semantic similarity search.

    Stores every resolved incident as a pattern:
      "When we saw X problem, found Y root cause, applied Z fix, got outcome W"

    Later incidents can query for similar past patterns to speed diagnosis
    and get success rate guidance.
    """

    def __init__(self, db_path: str = "./network_pattern_db.sqlite"):
        """
        Parameters
        ----------
        db_path : str
            Path to SQLite database file. Created if doesn't exist.
        """
        self.db_path = Path(db_path)
        self.embedding_model = None

        if EMBEDDINGS_AVAILABLE:
            try:
                self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("Embedding model loaded for semantic search")
            except Exception as e:
                logger.warning(f"Failed to load embedding model: {e}")

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Incidents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                problem_description TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                fix_applied TEXT NOT NULL,
                outcome TEXT NOT NULL,  -- fixed | degraded | no_change
                time_to_resolution_minutes REAL,
                operator_feedback TEXT,
                confidence REAL,
                recorded_at TEXT,
                embedding BLOB  -- JSON array of floats for semantic search
            )
        """)

        # Patterns table (aggregated: patterns that repeatedly cause same issues)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS failure_patterns (
                id TEXT PRIMARY KEY,
                pattern_name TEXT NOT NULL,
                pattern_description TEXT,
                trigger_description TEXT,  -- "MTU changes on 3+ interfaces"
                predicted_issue TEXT,       -- "latency spike"
                average_time_to_incident_minutes FLOAT,
                occurrence_count INTEGER,
                historical_accuracy REAL,   -- 0.0-1.0
                preventive_fix TEXT,
                last_updated TEXT
            )
        """)

        # Predictions table (track forecast accuracy for recalibration)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id TEXT PRIMARY KEY,
                problem_description TEXT NOT NULL,
                predicted_cause TEXT NOT NULL,
                predicted_at TEXT,
                actual_outcome TEXT,  -- filled in later
                prediction_was_correct BOOLEAN,
                accuracy_confidence REAL
            )
        """)

        conn.commit()
        conn.close()
        logger.info(f"Database initialized: {self.db_path}")

    def record_incident(self,
                        problem_description: str,
                        root_cause: str,
                        fix_applied: str,
                        outcome: str,
                        time_minutes: float,
                        operator_feedback: Optional[str] = None) -> str:
        """
        Store a resolved incident as a pattern for future reference.

        Parameters
        ----------
        problem_description : str
            User's problem description
        root_cause : str
            What was actually wrong
        fix_applied : str
            What we did to fix it
        outcome : str
            Did it work? "fixed" | "degraded" | "no_change"
        time_minutes : float
            Time from discovery to resolution
        operator_feedback : str, optional
            Operator's feedback on the diagnosis

        Returns
        -------
        str
            Incident ID for later reference
        """
        incident_id = str(uuid.uuid4())

        # Generate embedding for semantic search
        embedding = None
        if self.embedding_model:
            try:
                embedding = self.embedding_model.encode(problem_description)
            except Exception as e:
                logger.warning(f"Failed to embed problem: {e}")

        pattern = IncidentPattern(
            id=incident_id,
            problem_description=problem_description,
            root_cause=root_cause,
            fix_applied=fix_applied,
            outcome=outcome,
            time_to_resolution_minutes=time_minutes,
            operator_feedback=operator_feedback,
            confidence=0.5,  # Start at neutral, will be updated by feedback
            embedding=embedding.tolist() if embedding is not None else None,
        )

        # Store in database
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO incidents
            (id, problem_description, root_cause, fix_applied, outcome,
             time_to_resolution_minutes, operator_feedback, confidence, recorded_at, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pattern.id,
            pattern.problem_description,
            pattern.root_cause,
            pattern.fix_applied,
            pattern.outcome,
            pattern.time_to_resolution_minutes,
            pattern.operator_feedback,
            pattern.confidence,
            pattern.recorded_at,
            json.dumps(pattern.embedding) if pattern.embedding else None,
        ))

        conn.commit()
        conn.close()

        logger.info(f"Recorded incident {incident_id}: {problem_description[:60]}")
        return incident_id

    def find_similar(self,
                     problem_description: str,
                     top_k: int = 5,
                     min_confidence: float = 0.3) -> List[Tuple[float, IncidentPattern]]:
        """
        Find past incidents similar to this problem (semantic search).

        Parameters
        ----------
        problem_description : str
            Problem to find matches for
        top_k : int
            Maximum results to return
        min_confidence : float
            Only return patterns with confidence >= this threshold

        Returns
        -------
        List[(similarity_score, IncidentPattern)]
            Sorted by similarity (highest first)
        """
        if not EMBEDDINGS_AVAILABLE or not self.embedding_model:
            # Fallback: keyword matching
            return self._find_similar_keyword(problem_description, top_k)

        # Embed the problem
        try:
            query_embedding = self.embedding_model.encode(problem_description)
        except Exception as e:
            logger.warning(f"Failed to embed query: {e}")
            return []

        # Fetch all incidents
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM incidents WHERE embedding IS NOT NULL AND confidence >= ?",
                      (min_confidence,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            logger.info("No patterns found in database")
            return []

        # Compute cosine similarity to all
        similarities = []
        for row in rows:
            # Row: (id, problem_desc, root_cause, fix_applied, outcome,
            #       time_to_resolution, operator_feedback, confidence, recorded_at, embedding)
            try:
                stored_embedding = json.loads(row[9]) if row[9] else None
                if stored_embedding:
                    similarity = self._cosine_similarity(query_embedding, stored_embedding)
                    pattern = IncidentPattern(
                        id=row[0],
                        problem_description=row[1],
                        root_cause=row[2],
                        fix_applied=row[3],
                        outcome=row[4],
                        time_to_resolution_minutes=row[5],
                        operator_feedback=row[6],
                        confidence=row[7],
                        recorded_at=row[8],
                        embedding=stored_embedding,
                    )
                    similarities.append((similarity, pattern))
            except Exception as e:
                logger.warning(f"Error processing pattern {row[0]}: {e}")

        # Sort by similarity, return top K
        similarities.sort(reverse=True, key=lambda x: x[0])
        result = similarities[:top_k]

        logger.info(f"Found {len(result)} similar patterns (top {top_k})")
        return result

    def get_suggested_fix(self, problem_description: str) -> Optional[Dict[str, Any]]:
        """
        For a new problem, suggest a fix based on similar past incidents.

        Returns dict with:
        - suggested_fix: The command to run
        - root_cause: Diagnosis
        - confidence: How confident (based on success rate)
        - precedent_count: How many times we've seen this
        - success_rate: Percentage of time this fix worked

        Returns None if no similar patterns found.
        """
        similar = self.find_similar(problem_description, top_k=5)
        if not similar:
            return None

        # Group fixes by root cause
        fixes_by_cause = {}
        for sim_score, incident in similar:
            cause = incident.root_cause
            fix = incident.fix_applied
            outcome = incident.outcome

            if cause not in fixes_by_cause:
                fixes_by_cause[cause] = {
                    'fix': fix,
                    'outcomes': [],
                    'similarity_scores': [],
                    'base_confidence': incident.confidence,
                }

            fixes_by_cause[cause]['outcomes'].append(outcome)
            fixes_by_cause[cause]['similarity_scores'].append(sim_score)

        if not fixes_by_cause:
            return None

        # Pick best (highest success rate + confidence)
        best = max(
            fixes_by_cause.items(),
            key=lambda x: (
                x[1]['outcomes'].count('fixed') / len(x[1]['outcomes']),
                x[1]['base_confidence']
            )
        )

        cause, fix_data = best
        success_rate = fix_data['outcomes'].count('fixed') / len(fix_data['outcomes'])
        avg_sim = sum(fix_data['similarity_scores']) / len(fix_data['similarity_scores'])

        # Confidence = combination of success rate + base confidence + similarity
        confidence = (success_rate * 0.6 + fix_data['base_confidence'] * 0.3 + avg_sim * 0.1)

        return {
            'root_cause': cause,
            'suggested_fix': fix_data['fix'],
            'confidence': confidence,
            'success_rate': success_rate,
            'precedent_count': len(fix_data['outcomes']),
        }

    def update_confidence(self,
                         incident_id: str,
                         actual_outcome: str,
                         operator_feedback: Optional[str] = None) -> None:
        """
        Grade a fix based on actual outcome. Update confidence accordingly.

        Parameters
        ----------
        incident_id : str
            Which incident to update
        actual_outcome : str
            "fixed" | "degraded" | "no_change"
        operator_feedback : str, optional
            Operator's comment on the resolution
        """
        # Adjust confidence based on outcome
        confidence_delta = {
            "fixed": 0.1,         # Success: boost confidence
            "degraded": -0.2,     # Made worse: penalize significantly
            "no_change": 0.0,     # Didn't help, but not harmful
        }.get(actual_outcome, 0.0)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE incidents
            SET outcome = ?, operator_feedback = ?, confidence = MIN(1.0, MAX(0.0, confidence + ?))
            WHERE id = ?
        """, (actual_outcome, operator_feedback, confidence_delta, incident_id))

        conn.commit()
        conn.close()

        logger.info(f"Updated incident {incident_id}: outcome={actual_outcome}, "
                   f"confidence_delta={confidence_delta}")

    def record_failure_pattern(self,
                               pattern_name: str,
                               pattern_description: str,
                               triggers: List[str],  # e.g., ["MTU change", "interface flap"]
                               predicted_issue: str,
                               occurrence_count: int = 1,
                               accuracy: float = 0.5,
                               preventive_fix: Optional[str] = None) -> str:
        """
        Record a learned pattern: "When X happens, Y issue results".

        Used for forecasting (Path A) and predictive alerts.
        """
        pattern_id = str(uuid.uuid4())
        trigger_desc = " + ".join(triggers)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO failure_patterns
            (id, pattern_name, pattern_description, trigger_description, predicted_issue,
             average_time_to_incident_minutes, occurrence_count, historical_accuracy,
             preventive_fix, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pattern_id, pattern_name, pattern_description, trigger_desc,
            predicted_issue, 5.0, occurrence_count, accuracy,
            preventive_fix, datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()

        logger.info(f"Recorded failure pattern: {pattern_name}")
        return pattern_id

    def get_failure_patterns(self) -> List[Dict[str, Any]]:
        """Get all learned failure patterns for forecasting."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM failure_patterns ORDER BY historical_accuracy DESC")
        rows = cursor.fetchall()
        conn.close()

        patterns = []
        for row in rows:
            patterns.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'triggers': row[3].split(" + ") if row[3] else [],
                'predicted_issue': row[4],
                'average_time_to_incident': row[5],
                'occurrence_count': row[6],
                'historical_accuracy': row[7],
                'preventive_fix': row[8],
            })

        return patterns

    def get_stats(self) -> Dict[str, Any]:
        """Database statistics."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM incidents")
        incident_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM failure_patterns")
        pattern_count = cursor.fetchone()[0]

        cursor.execute("SELECT AVG(confidence) FROM incidents WHERE outcome = 'fixed'")
        avg_success_confidence = cursor.fetchone()[0] or 0.0

        conn.close()

        return {
            'total_incidents': incident_count,
            'total_patterns': pattern_count,
            'avg_success_confidence': avg_success_confidence,
        }

    # ── Helper methods ─────────────────────────────────────────────────────────

    def _find_similar_keyword(self, problem: str, top_k: int) -> List[Tuple[float, IncidentPattern]]:
        """Fallback keyword-based similarity when embeddings unavailable."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM incidents")
        rows = cursor.fetchall()
        conn.close()

        keywords = set(problem.lower().split())
        results = []

        for row in rows:
            problem_keywords = set(row[1].lower().split())  # problem_description
            overlap = len(keywords & problem_keywords) / len(keywords | problem_keywords)

            if overlap > 0.2:  # At least 20% keyword overlap
                pattern = IncidentPattern(
                    id=row[0],
                    problem_description=row[1],
                    root_cause=row[2],
                    fix_applied=row[3],
                    outcome=row[4],
                    time_to_resolution_minutes=row[5],
                    operator_feedback=row[6],
                    confidence=row[7],
                    recorded_at=row[8],
                )
                results.append((overlap, pattern))

        results.sort(reverse=True, key=lambda x: x[0])
        return results[:top_k]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b))
        mag_a = sum(x * x for x in a) ** 0.5
        mag_b = sum(x * x for x in b) ** 0.5

        if mag_a == 0 or mag_b == 0:
            return 0.0

        return dot_product / (mag_a * mag_b)
