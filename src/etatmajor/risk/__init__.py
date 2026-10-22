"""Risk authority.

The risk governor is independent from the strategies: a strategy proposes, the
risk authority decides. In Phase 2 only the *contract* and a minimal
implementation are provided; the advanced limits (daily loss, global drawdown,
correlated exposure, prop firm challenge profiles) belong to Phase 5.

No code path in the replay engine may submit an order without a positive
decision from this authority.
"""
