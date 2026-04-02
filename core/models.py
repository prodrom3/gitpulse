from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RepoStatus(Enum):
    UPDATED = "updated"
    UP_TO_DATE = "up-to-date"
    FETCHED = "fetched"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class RepoResult:
    path: str
    status: RepoStatus
    reason: Optional[str] = None
    branch: Optional[str] = None
    remote_url: Optional[str] = None

    def to_dict(self) -> dict[str, Optional[str]]:
        return {
            "path": self.path,
            "status": self.status.value,
            "reason": self.reason,
            "branch": self.branch,
            "remote_url": self.remote_url,
        }
