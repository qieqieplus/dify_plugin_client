from collections.abc import Sequence
from typing import Any

import httpx

from ..entities.bundle import PluginBundleDependency
from ..entities.plugin import (
    MissingPluginDependency,
    PluginDeclaration,
    PluginEntity,
    PluginInstallation,
    PluginInstallationSource,
)
from ..entities.plugin_daemon import (
    PluginDecodeResponse,
    PluginInstallTask,
    PluginInstallTaskStartResponse,
    PluginListResponse,
    PluginReadmeResponse,
    PluginToolProviderEntity,
)
from ..entities.tools import ToolInvokeMessage
from .base import BasePluginClient


def resolve_dify_schema_refs(schema: dict) -> dict:
    """
    Resolve simple in-document JSON Schema references.

    Supports `#/$defs/<name>` and `#/definitions/<name>` references by
    replacing the `$ref` node with the referenced definition. Falls back to
    returning the original node when the reference cannot be resolved.
    """

    if not isinstance(schema, dict):
        return schema

    definitions = schema.get("$defs") or schema.get("definitions") or {}

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and (ref.startswith("#/$defs/") or ref.startswith("#/definitions/")):
                key = ref.rsplit("/", 1)[-1]
                target = definitions.get(key)
                if isinstance(target, dict):
                    # merge resolved target with current node (sans $ref) so local overrides win
                    resolved_target = _resolve(target)
                    merged = {**resolved_target, **{k: v for k, v in node.items() if k != "$ref"}}
                    return merged
                return node
            return {k: _resolve(v) for k, v in node.items()}

        if isinstance(node, list):
            return [_resolve(item) for item in node]

        return node

    return _resolve(schema)


def _parse_tool_provider_id(tool_provider: str) -> tuple[str, str]:
    """
    Parse a tool provider id into (plugin_id, provider_name).

    Accepts either:
    - "plugin_id/provider_name" (legacy)
    - "organization/plugin_name/provider_name" (preferred, matches main app)
    """

    parts = tool_provider.split("/")
    if len(parts) == 2:
        return tool_provider, parts[1]
    if len(parts) == 3:
        return "/".join(parts[:2]), parts[2]

    raise ValueError(
        "Invalid provider format. Expected 'plugin_id/provider_name' or "
        "'organization/plugin_name/provider_name'."
    )


class DifyPluginClient(BasePluginClient):
    def fetch_plugin_readme(self, tenant_id: str, plugin_unique_identifier: str, language: str) -> str:
        """
        Fetch plugin readme
        """
        try:
            response = self._request_with_plugin_daemon_response(
                "GET",
                f"plugin/{tenant_id}/management/fetch/readme",
                PluginReadmeResponse,
                params={
                    "tenant_id": tenant_id,
                    "plugin_unique_identifier": plugin_unique_identifier,
                    "language": language,
                },
            )
            return response.content
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return ""
            raise e

    def fetch_plugin_by_identifier(
        self,
        tenant_id: str,
        identifier: str,
    ) -> bool:
        return self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/fetch/identifier",
            bool,
            params={"plugin_unique_identifier": identifier},
        )

    def list_plugins(self, tenant_id: str) -> list[PluginEntity]:
        result = self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/list",
            PluginListResponse,
            params={"page": 1, "page_size": 256, "response_type": "paged"},
        )
        return result.list

    def list_plugins_with_total(self, tenant_id: str, page: int, page_size: int) -> PluginListResponse:
        return self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/list",
            PluginListResponse,
            params={"page": page, "page_size": page_size, "response_type": "paged"},
        )

    def upload_pkg(
        self,
        tenant_id: str,
        pkg: bytes,
        verify_signature: bool = False,
    ) -> PluginDecodeResponse:
        """
        Upload a plugin package and return the plugin unique identifier.
        """
        body = {
            "dify_pkg": ("dify_pkg", pkg, "application/octet-stream"),
        }

        data = {
            "verify_signature": "true" if verify_signature else "false",
        }

        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/install/upload/package",
            PluginDecodeResponse,
            files=body,
            data=data,
        )

    def upload_bundle(
        self,
        tenant_id: str,
        bundle: bytes,
        verify_signature: bool = False,
    ) -> Sequence[PluginBundleDependency]:
        """
        Upload a plugin bundle and return the dependencies.
        """
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/install/upload/bundle",
            list[PluginBundleDependency],
            files={"dify_bundle": ("dify_bundle", bundle, "application/octet-stream")},
            data={"verify_signature": "true" if verify_signature else "false"},
        )

    def install_from_identifiers(
        self,
        tenant_id: str,
        identifiers: Sequence[str],
        source: PluginInstallationSource,
        metas: list[dict],
    ) -> PluginInstallTaskStartResponse:
        """
        Install a plugin from an identifier.
        """
        if not identifiers:
            raise ValueError("identifiers must be provided")
        if len(metas) != len(identifiers):
            raise ValueError("metas length must match identifiers")
        if not all(isinstance(meta, dict) for meta in metas):
            raise ValueError("metas must be a list of dictionaries")

        # exception will be raised if the request failed
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/install/identifiers",
            PluginInstallTaskStartResponse,
            data={
                "plugin_unique_identifiers": identifiers,
                "source": source,
                "metas": metas,
            },
            headers={"Content-Type": "application/json"},
        )

    def fetch_plugin_installation_tasks(self, tenant_id: str, page: int, page_size: int) -> Sequence[PluginInstallTask]:
        """
        Fetch plugin installation tasks.
        """
        return self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/install/tasks",
            list[PluginInstallTask],
            params={"page": page, "page_size": page_size},
        )

    def fetch_plugin_installation_task(self, tenant_id: str, task_id: str) -> PluginInstallTask:
        """
        Fetch a plugin installation task.
        """
        return self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/install/tasks/{task_id}",
            PluginInstallTask,
        )

    def delete_plugin_installation_task(self, tenant_id: str, task_id: str) -> bool:
        """
        Delete a plugin installation task.
        """
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/install/tasks/{task_id}/delete",
            bool,
        )

    def delete_all_plugin_installation_task_items(self, tenant_id: str) -> bool:
        """
        Delete all plugin installation task items.
        """
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/install/tasks/delete_all",
            bool,
        )

    def delete_plugin_installation_task_item(self, tenant_id: str, task_id: str, identifier: str) -> bool:
        """
        Delete a plugin installation task item.
        """
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/install/tasks/{task_id}/delete/{identifier}",
            bool,
        )

    def fetch_plugin_manifest(self, tenant_id: str, plugin_unique_identifier: str) -> PluginDeclaration:
        """
        Fetch a plugin manifest.
        """

        return self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/fetch/manifest",
            PluginDeclaration,
            params={"plugin_unique_identifier": plugin_unique_identifier},
        )

    def decode_plugin_from_identifier(self, tenant_id: str, plugin_unique_identifier: str) -> PluginDecodeResponse:
        """
        Decode a plugin from an identifier.
        """
        return self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/decode/from_identifier",
            PluginDecodeResponse,
            params={"plugin_unique_identifier": plugin_unique_identifier},
        )

    def fetch_plugin_installation_by_ids(
        self, tenant_id: str, plugin_ids: Sequence[str]
    ) -> Sequence[PluginInstallation]:
        """
        Fetch plugin installations by ids.
        """
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/installation/fetch/batch",
            list[PluginInstallation],
            data={"plugin_ids": plugin_ids},
            headers={"Content-Type": "application/json"},
        )

    def fetch_missing_dependencies(
        self, tenant_id: str, plugin_unique_identifiers: list[str]
    ) -> list[MissingPluginDependency]:
        """
        Fetch missing dependencies
        """
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/installation/missing",
            list[MissingPluginDependency],
            data={"plugin_unique_identifiers": plugin_unique_identifiers},
            headers={"Content-Type": "application/json"},
        )

    def uninstall(self, tenant_id: str, plugin_installation_id: str) -> bool:
        """
        Uninstall a plugin.
        """
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/uninstall",
            bool,
            data={
                "plugin_installation_id": plugin_installation_id,
            },
            headers={"Content-Type": "application/json"},
        )

    def upgrade_plugin(
        self,
        tenant_id: str,
        original_plugin_unique_identifier: str,
        new_plugin_unique_identifier: str,
        source: PluginInstallationSource,
        meta: dict,
    ) -> PluginInstallTaskStartResponse:
        """
        Upgrade a plugin.
        """
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/install/upgrade",
            PluginInstallTaskStartResponse,
            data={
                "original_plugin_unique_identifier": original_plugin_unique_identifier,
                "new_plugin_unique_identifier": new_plugin_unique_identifier,
                "source": source,
                "meta": meta,
            },
            headers={"Content-Type": "application/json"},
        )

    def check_tools_existence(self, tenant_id: str, provider_ids: Sequence[dict]) -> Sequence[bool]:
        """
        Check if the tools exist
        """
        return self._request_with_plugin_daemon_response(
            "POST",
            f"plugin/{tenant_id}/management/tools/check_existence",
            list[bool],
            data={
                "provider_ids": [
                    {
                        "plugin_id": provider_id.get("plugin_id"),
                        "provider_name": provider_id.get("provider_name"),
                    }
                    for provider_id in provider_ids
                ]
            },
            headers={"Content-Type": "application/json"},
        )

    def fetch_tool_providers(self, tenant_id: str) -> list[PluginToolProviderEntity]:
        """
        Fetch tool providers for the given tenant.
        """

        def transformer(json_response: dict[str, Any]):
            for provider in json_response.get("data", []):
                declaration = provider.get("declaration", {}) or {}
                provider_name = declaration.get("identity", {}).get("name")
                for tool in declaration.get("tools", []):
                    tool["identity"]["provider"] = provider_name
                    # resolve refs
                    if tool.get("output_schema"):
                        tool["output_schema"] = resolve_dify_schema_refs(tool["output_schema"])

            return json_response

        response = self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/tools",
            list[PluginToolProviderEntity],
            params={"page": 1, "page_size": 256},
            transformer=transformer,
        )

        for provider in response:
            provider.declaration.identity.name = f"{provider.plugin_id}/{provider.declaration.identity.name}"

            # override the provider name for each tool to plugin_id/provider_name
            for tool in provider.declaration.tools:
                tool.identity.provider = provider.declaration.identity.name

        return response

    def fetch_tool_provider(self, tenant_id: str, provider: str) -> PluginToolProviderEntity:
        """
        Fetch tool provider for the given tenant and plugin.
        """
        plugin_id, provider_name = _parse_tool_provider_id(provider)

        def transformer(json_response: dict[str, Any]):
            data = json_response.get("data")
            if data:
                for tool in data.get("declaration", {}).get("tools", []):
                    tool["identity"]["provider"] = provider_name
                    # resolve refs
                    if tool.get("output_schema"):
                        tool["output_schema"] = resolve_dify_schema_refs(tool["output_schema"])

            return json_response

        response = self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/tool",
            PluginToolProviderEntity,
            params={"provider": provider_name, "plugin_id": plugin_id},
            transformer=transformer,
        )

        response.declaration.identity.name = f"{response.plugin_id}/{response.declaration.identity.name}"

        # override the provider name for each tool to plugin_id/provider_name
        for tool in response.declaration.tools:
            tool.identity.provider = response.declaration.identity.name

        return response

    def invoke(
        self,
        tenant_id: str,
        user_id: str,
        tool_provider: str,
        tool_name: str,
        credentials: dict[str, Any],
        tool_parameters: dict[str, Any],
    ):
        """
        Invoke the tool with the given tenant, user, plugin, provider, name, credentials and parameters.
        """

        plugin_id, provider_name = _parse_tool_provider_id(tool_provider)

        normalized_parameters = self._normalize_tool_parameters(
            tenant_id=tenant_id,
            tool_provider=tool_provider,
            tool_name=tool_name,
            tool_parameters=tool_parameters,
        )

        response = self._request_with_plugin_daemon_response_stream(
            "POST",
            f"plugin/{tenant_id}/dispatch/tool/invoke",
            ToolInvokeMessage,
            data={
                "user_id": user_id,
                "data": {
                    "provider": provider_name,
                    "tool": tool_name,
                    "credentials": credentials,
                    "tool_parameters": normalized_parameters,
                },
            },
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        return response

    def _normalize_tool_parameters(
        self,
        tenant_id: str,
        tool_provider: str,
        tool_name: str,
        tool_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Coerce tool parameters to the types declared by the tool provider.

        Fetches the provider declaration to apply type-aware casting similar to
        the main Dify controller. Parameters not declared by the tool are passed
        through unchanged to preserve backward compatibility.
        """

        provider = self.fetch_tool_provider(tenant_id, tool_provider)
        tool = next((t for t in provider.declaration.tools if t.identity.name == tool_name), None)
        if tool is None:
            raise ValueError(f"Tool `{tool_name}` not found for provider `{tool_provider}`")

        normalized: dict[str, Any] = {}

        for param in tool.parameters:
            raw_value = tool_parameters.get(param.name)
            normalized[param.name] = self._cast_tool_parameter_value(param, raw_value)

        # Preserve any extra parameters (for forwards compatibility)
        for key, value in tool_parameters.items():
            if key not in normalized:
                normalized[key] = value

        return normalized

    @staticmethod
    def _cast_tool_parameter_value(param: Any, value: Any) -> Any:
        """
        Cast a tool parameter value based on the tool's parameter declaration.
        """

        # Import locally to avoid circular imports at module load.
        from ..entities.tools import ToolParameter

        if not isinstance(param, ToolParameter):
            return value

        match param.type:
            case ToolParameter.ToolParameterType.STRING | ToolParameter.ToolParameterType.SECRET_INPUT:
                if value is None:
                    if param.required:
                        raise ValueError(f"tool parameter {param.name} is required")
                    return ""
                return value if isinstance(value, str) else str(value)
            case ToolParameter.ToolParameterType.SELECT:
                if value is None:
                    if param.required:
                        raise ValueError(f"tool parameter {param.name} is required")
                    return ""
                if param.options:
                    options = param.options
                    if value not in options:
                        raise ValueError(f"tool parameter {param.name} value {value} not in options {options}")
                return value if isinstance(value, str) else str(value)
            case ToolParameter.ToolParameterType.BOOLEAN:
                if value is None:
                    return False
                if isinstance(value, str):
                    lowered = value.lower()
                    if lowered in {"true", "yes", "y", "1"}:
                        return True
                    if lowered in {"false", "no", "n", "0"}:
                        return False
                return bool(value)
            case ToolParameter.ToolParameterType.NUMBER:
                if value is None:
                    return 0
                if isinstance(value, (int, float)):
                    return value
                if isinstance(value, str) and value:
                    try:
                        return float(value) if "." in value else int(value)
                    except ValueError:
                        raise ValueError(f"tool parameter {param.name} expects a number")
                raise ValueError(f"tool parameter {param.name} expects a number")
            case ToolParameter.ToolParameterType.FILE:
                if isinstance(value, list):
                    if len(value) != 1:
                        raise ValueError("This parameter only accepts one file but got multiple files while invoking.")
                    return value[0]
                return value
            case ToolParameter.ToolParameterType.FILES | ToolParameter.ToolParameterType.ARRAY:
                if value is None:
                    return []
                return value if isinstance(value, list) else [value]
            case _:
                return value
