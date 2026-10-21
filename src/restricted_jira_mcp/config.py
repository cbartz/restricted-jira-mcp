from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLACEHOLDER = "CHANGE_ME"


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    allowed_projects: tuple[str, ...]
    allowed_custom_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class HTTPConfig:
    host: str
    port: int
    client_token: str
    allowed_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServerConfig:
    jira: JiraConfig
    http: HTTPConfig | None = None


def load_config(path: str | Path) -> ServerConfig:
    """Load and validate the JSON config file.

    The "http" section is optional; without it the config only serves stdio.
    Any unusable value — unknown keys included, so a typo never silently drops
    a restriction — raises ValueError naming the offending key.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise ValueError(f"Could not read config file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file {path}: {exc}") from exc

    _check_keys(data, "config", required=("jira",), optional=("http",))
    http = data.get("http")
    return ServerConfig(
        jira=_jira_config(data["jira"]),
        http=None if http is None else _http_config(http),
    )


def _jira_config(section: Any) -> JiraConfig:
    _check_keys(
        section,
        "jira",
        required=("base_url", "email", "api_token", "allowed_projects"),
        optional=("allowed_custom_fields",),
    )
    projects = _string_list("jira.allowed_projects", section["allowed_projects"])
    if not projects:
        raise ValueError("jira.allowed_projects must list at least one project")
    return JiraConfig(
        base_url=_required_string(section, "base_url", "jira").rstrip("/"),
        email=_required_string(section, "email", "jira"),
        api_token=_required_string(section, "api_token", "jira"),
        allowed_projects=projects,
        allowed_custom_fields=_string_list(
            "jira.allowed_custom_fields", section.get("allowed_custom_fields", [])
        ),
    )


def _http_config(section: Any) -> HTTPConfig:
    _check_keys(
        section,
        "http",
        required=("bind_address", "client_token"),
        optional=("allowed_hosts",),
    )
    host, port = _parse_bind_address(_required_string(section, "bind_address", "http"))
    allowed_hosts = _string_list("http.allowed_hosts", section.get("allowed_hosts", []))
    if _is_unspecified(host) and not allowed_hosts:
        raise ValueError(
            f"http.bind_address {host} listens on every interface; list the Host "
            "values clients use in http.allowed_hosts"
        )

    return HTTPConfig(
        host=host,
        port=port,
        client_token=_required_string(section, "client_token", "http"),
        allowed_hosts=allowed_hosts,
    )


def _parse_bind_address(value: str) -> tuple[str, int]:
    """Split "host:port" (IPv6 hosts in brackets) into the bare host and port."""
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError(
            f"http.bind_address must be host:port with a port from 1 to 65535, got {value!r}"
        )
    return host.removeprefix("[").removesuffix("]"), int(port)


def _is_unspecified(host: str) -> bool:
    """True for any spelling of the all-interfaces address (0.0.0.0, ::, 0:0:...:0)."""
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def _check_keys(section: Any, name: str, required: tuple[str, ...], optional: tuple[str, ...]) -> None:
    if not isinstance(section, dict):
        raise ValueError(f"{name} must be a JSON object")
    missing = [key for key in required if key not in section]
    if missing:
        raise ValueError(f"{name} is missing required keys: {', '.join(missing)}")
    unknown = sorted(set(section) - set(required) - set(optional))
    if unknown:
        raise ValueError(f"{name} has unknown keys: {', '.join(unknown)}")


def _required_string(section: dict, key: str, name: str) -> str:
    """Return a required non-empty string value, rejecting the example's placeholder."""
    value = section[key]
    if not isinstance(value, str) or not value.strip() or value.strip() == PLACEHOLDER:
        raise ValueError(f"{name}.{key} must be set (not empty or {PLACEHOLDER})")
    return value.strip()


def _string_list(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    items = tuple(item.strip() for item in value)
    if any(not item or item == PLACEHOLDER for item in items):
        raise ValueError(f"{name} entries must be set (not empty or {PLACEHOLDER})")
    return items
