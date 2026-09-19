"""Evaluation: case scripts, the session pipeline, replay, metrics and ablations.

A case script is the source of truth for a test case. It drives transcript replay today,
audio assembly later, and carries the labels (first tactic, expected warning, harm) that
were written by hand rather than derived from Chaukas's own detectors.
"""
