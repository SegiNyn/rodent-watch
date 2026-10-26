from dataclasses import dataclass


@dataclass
class SightingGate:
    """One alert until an observed absence, plus a minimum alert interval.

    All times are video seconds, independent of inference speed.
    A continuous sighting never re-alerts merely because cooldown expired.
    """
    clear_seconds: float = 5.0
    cooldown_seconds: float = 30.0
    active: bool = False
    absent_since: float | None = None
    last_alert: float = float("-inf")

    def update(self, timestamp: float, detected: bool) -> bool:
        if not detected:
            if self.absent_since is None:
                self.absent_since = timestamp
            if timestamp - self.absent_since >= self.clear_seconds:
                self.active = False
            return False
        self.absent_since = None
        if self.active or timestamp - self.last_alert < self.cooldown_seconds:
            return False
        self.active = True
        self.last_alert = timestamp
        return True
