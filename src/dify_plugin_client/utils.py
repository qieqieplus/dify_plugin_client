from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .entities.plugin import PluginResourceRequirements
from .impl.base import PluginConfig
from .impl.plugin import DifyPluginClient

DEFAULT_CONFIG_PATH = Path.home() / ".dify"
DEFAULT_URL = "http://localhost:5002"
DEFAULT_KEY = "plugin-api-key"
DEFAULT_TIMEOUT = 300.0


def json_default_serializer(obj: Any) -> Any:
    """
    Serializer that can handle Pydantic models and bytes.
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def parse_json_arg(value: str | None, file_path: str | None, default: dict[str, Any]) -> dict[str, Any]:
    """
    Parse a JSON argument from a string or a file.
    """
    if value and file_path:
        raise ValueError("Provide either the inline value or the file path, not both.")
    if file_path:
        return json.loads(Path(file_path).read_text())
    if value:
        return json.loads(value)
    return default


def format_permission_summary(permission: PluginResourceRequirements.Permission | None) -> str:
    """
    Collapse a permission object into a short, human-friendly string.
    """

    if permission is None:
        return "none"

    parts: list[str] = []

    if permission.tool and permission.tool.enabled:
        parts.append("tool")

    if permission.model:
        model_flags: list[str] = []
        if permission.model.enabled:
            model_flags.append("any")
        for attr, label in [
            ("llm", "llm"),
            ("text_embedding", "embedding"),
            ("rerank", "rerank"),
            ("tts", "tts"),
            ("speech2text", "speech2text"),
            ("moderation", "moderation"),
        ]:
            if getattr(permission.model, attr):
                model_flags.append(label)
        if model_flags:
            parts.append(f"model({', '.join(model_flags)})")

    if permission.node and permission.node.enabled:
        parts.append("node")

    if permission.endpoint and permission.endpoint.enabled:
        parts.append("endpoint")

    if permission.storage and permission.storage.enabled:
        size = f", size={permission.storage.size}" if permission.storage.size else ""
        parts.append(f"storage{size}")

    return ", ".join(parts) if parts else "none"


def plugin_permission_summary(plugin: Any) -> str:
    """
    Summarize the permissions declared by a plugin entity or declaration.
    """
    declaration = getattr(plugin, "declaration", None)
    resource = getattr(declaration, "resource", None) if declaration else None
    permission = getattr(resource, "permission", None) if resource else None
    return format_permission_summary(permission)


def build_permission_lookup(client: DifyPluginClient, tenant_id: str | None) -> dict[str, str]:
    """
    Build a mapping of plugin_unique_identifier -> permission summary.

    If the lookup fails (e.g., due to permissions), return an empty mapping so
    callers can still proceed with degraded output.
    """

    try:
        plugins = client.list_plugins(tenant_id)
    except Exception:
        return {}

    return {plugin.plugin_unique_identifier: plugin_permission_summary(plugin) for plugin in plugins}


def load_settings(path: Path) -> dict[str, Any]:
    """
    Load optional defaults from a config file (expects a JSON object).
    """

    resolved = path.expanduser()
    if not resolved.exists():
        return {}
    if resolved.is_dir():
        raise ValueError(f"Config path {resolved} is a directory, expected a file.")

    try:
        raw = resolved.read_text().strip()
    except OSError as exc:
        raise ValueError(f"Failed to read config file {resolved}: {exc}") from exc

    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Config file must be valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Config file must contain a JSON object at the top level.")

    return parsed


def coerce_timeout(*candidates: Any, default: float = DEFAULT_TIMEOUT) -> float:
    """
    Return the first non-null candidate timeout as a float; fall back to default.
    """
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, (int, float)):
            return float(candidate)
        if isinstance(candidate, str):
            try:
                return float(candidate)
            except ValueError as exc:
                raise ValueError("Timeout must be a number") from exc
    return default


def resolve_client_config(
    url: str | None = None,
    key: str | None = None,
    timeout: float | str | None = None,
    config_path: str | Path | None = DEFAULT_CONFIG_PATH,
    env: Mapping[str, str] | None = None,
) -> PluginConfig:
    """
    Build a PluginConfig using the same precedence as the CLI:
    explicit args > environment > config file > defaults.
    """
    env_map = env or os.environ
    settings = load_settings(Path(config_path)) if config_path else {}

    resolved_url = url or env_map.get("DIFY_PLUGIN_DAEMON_URL") or settings.get("url") or DEFAULT_URL
    resolved_key = key or env_map.get("DIFY_PLUGIN_DAEMON_KEY") or settings.get("key") or DEFAULT_KEY
    resolved_timeout = coerce_timeout(
        timeout,
        env_map.get("DIFY_PLUGIN_DAEMON_TIMEOUT"),
        settings.get("timeout"),
        DEFAULT_TIMEOUT,
    )

    return PluginConfig(
        url=resolved_url,
        key=resolved_key,
        timeout=resolved_timeout,
    )

