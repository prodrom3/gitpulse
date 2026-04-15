from dataclasses import dataclass
from enum import Enum


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
    reason: str | None = None
    branch: str | None = None
    remote_url: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "path": self.path,
            "status": self.status.value,
            "reason": self.reason,
            "branch": self.branch,
            "remote_url": self.remote_url,
        }
