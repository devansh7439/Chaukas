"""Signal extraction: turns transcript segments into typed evidence, instantly, on CPU.

Pipeline per segment: normalise → tokenise → lexicon scan (Aho–Corasick) → request fast
path, negation and suppression → keyword signals; plus the user-digits rule.
"""
