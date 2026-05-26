from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    allowed_projects: tuple[str, ...]
    allowed_custom_fields: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "JiraConfig":
        missing = [
            name
            for name in (
                "JIRA_BASE_URL",
                "JIRA_EMAIL",
                "JIRA_API_TOKEN",
                "JIRA_ALLOWED_PROJECTS",
            )
            if not os.environ.get(name)
        ]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        return cls(
            base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
            email=os.environ["JIRA_EMAIL"],
            api_token=os.environ["JIRA_API_TOKEN"],
            allowed_projects=_csv_env("JIRA_ALLOWED_PROJECTS"),
            allowed_custom_fields=_csv_env("JIRA_ALLOWED_CUSTOM_FIELDS"),
        )


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.environ.get(name, "").split(",") if part.strip())
