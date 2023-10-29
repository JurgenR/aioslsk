from dataclasses import dataclass, field
from datetime import datetime
from .user.model import User


@dataclass
class Session:
    user: User
    ip_address: str
    greeting: str
    client_version: int
    minor_version: int
    logged_in_at: datetime = field(default_factory=datetime.utcnow)
    privileges_time_left: int = 0

    @property
    def privileged(self) -> bool:
        return self.privileges_time_left > 0
