"""HiddenPivot: rejected low plus a compressed range's confirmed expansion."""

from sequoia_x.strategy.failed_new_low import FailedNewLowStrategy


class HiddenPivotStrategy(FailedNewLowStrategy):
    webhook_key = "hidden_pivot"
    signal_key = "hidden_pivot"
    score_key = "hidden_pivot_score"
