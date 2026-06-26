"""
core/intelligence/learning
===========================
Organizational learning — institutional memory, not model weights.

Every workflow feeds one funnel; the funnel improves every dimension; periodic
retrospectives mine the whole corpus for emergent patterns, repeated mistakes,
and winning strategies. The longer the platform runs, the more of its own
history it has read — and the better it gets, without retraining the LLM.

  from core.intelligence.learning import (
      get_learning_engine, learn_from, wire_learning, LearningEvent)

  wire_learning()                                  # at startup
  learn_from(LearningEvent(kind="deployment", success=True,
             intent="add ospf", device="...", protocol="ospf",
             commands=[...], stated_confidence=0.8))
  get_learning_engine().retrospect()               # after-action review
  get_learning_engine().lessons("ospf adjacency stuck")   # recall
"""
from core.intelligence.learning.engine import (
    LearningEngine, get_learning_engine, learn_from, wire_learning,
)
from core.intelligence.learning.base import (
    Lesson, LessonType, LearningEvent, LessonStore,
)

__all__ = [
    "LearningEngine", "get_learning_engine", "learn_from", "wire_learning",
    "Lesson", "LessonType", "LearningEvent", "LessonStore",
]
