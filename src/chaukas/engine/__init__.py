"""Risk engine: attack-chain matching, decaying evidence, gates, levels and special rules.

The engine is a plain object driven by method calls (segments, signals, context, LLM
assessments, dismissals) and queried with ``evaluate(now)``. It has no threads and no
event-bus dependency, so replay, evaluation and tests drive it deterministically; the live
pipeline adapts bus events onto the same methods.
"""
