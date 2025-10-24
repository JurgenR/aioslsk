from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from .user.model import User


@dataclass(slots=True)
class Session:
    user: User
    ip_address: str
    greeting: str
    client_version: int
    minor_version: int
    logged_in_at: datetime = field(default_factory=partial(datetime.now, timezone.utc))
    privileges_time_left: int = 0

    @property
    def privileged(self) -> bool:
        return self.privileges_time_left > 0
