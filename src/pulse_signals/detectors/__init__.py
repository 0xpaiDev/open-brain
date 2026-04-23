"""Phase 1 detectors: focus, opportunity, open.

Each module exposes:
  NAME: str                             — matches signal_type in DB
  detect(ctx, ...) -> Signal | None     — pure function over MorningContext
"""
