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
                "JIRA_ALLOWED_PROJECTS",
            )
            if not os.environ.get(name)
        ]
        if missing:
            # When checking for tokens, we need to include JIRA_API_TOKEN in the error message
            # if neither token variable is set
            if not os.environ.get("JIRA_API_TOKEN") and not os.environ.get("JIRA_API_TOKEN_FILE"):
                missing.append("JIRA_API_TOKEN")
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        api_token = _load_api_token()

        return cls(
            base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
            email=os.environ["JIRA_EMAIL"],
            api_token=api_token,
            allowed_projects=_csv_env("JIRA_ALLOWED_PROJECTS"),
            allowed_custom_fields=_csv_env("JIRA_ALLOWED_CUSTOM_FIELDS"),
        )


def _load_api_token() -> str:
    """Load API token from environment variable or file.
    
    Returns:
        The API token string
        
    Raises:
        ValueError: If both JIRA_API_TOKEN and JIRA_API_TOKEN_FILE are set,
                    or if JIRA_API_TOKEN_FILE points to a missing or empty file
    """
    token_from_env = os.environ.get("JIRA_API_TOKEN")
    token_from_file = os.environ.get("JIRA_API_TOKEN_FILE")
    
    if token_from_env and token_from_file:
        raise ValueError("Set only one of JIRA_API_TOKEN and JIRA_API_TOKEN_FILE")
    
    if token_from_env:
        return token_from_env
    
    if token_from_file:
        try:
            with open(token_from_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                
            if not content:
                raise ValueError(f"Token file is empty: {token_from_file}")
                
            return content
        except FileNotFoundError:
            raise ValueError(f"Token file not found: {token_from_file}")
    
    # Neither is set
    raise ValueError("Missing required environment variables: JIRA_API_TOKEN")


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.environ.get(name, "").split(",") if part.strip())
