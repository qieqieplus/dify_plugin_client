from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dify_plugin_client import DifyPluginClient, PluginConfig
from dify_plugin_client.entities.tools import ToolInvokeMessage


def _json_default_serializer(obj: Any) -> Any:
    """
    Serializer that can handle Pydantic models and bytes.
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _parse_json_arg(value: str | None, file_path: str | None, default: dict[str, Any]) -> dict[str, Any]:
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


def _build_client(args: argparse.Namespace) -> DifyPluginClient:
    config = PluginConfig(
        url=args.url,
        key=args.key,
        timeout=args.timeout,
    )
    return DifyPluginClient(config)


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--url",
        default=os.getenv("DIFY_PLUGIN_DAEMON_URL", "http://localhost:5002"),
        help="Plugin daemon URL (env: DIFY_PLUGIN_DAEMON_URL)",
    )
    parser.add_argument(
        "--key",
        default=os.getenv("DIFY_PLUGIN_DAEMON_KEY", "plugin-api-key"),
        help="Plugin daemon API key (env: DIFY_PLUGIN_DAEMON_KEY)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("DIFY_PLUGIN_DAEMON_TIMEOUT", "300")),
        help="Request timeout in seconds (env: DIFY_PLUGIN_DAEMON_TIMEOUT)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dify-plugin-client",
        description="Interact with a Dify plugin daemon from the command line.",
    )
    _add_common_arguments(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List installed plugins for a tenant.")
    list_parser.add_argument("--tenant", required=True, help="Tenant ID.")
    list_parser.add_argument("--page", type=int, default=1, help="Page number (default: 1).")
    list_parser.add_argument("--page-size", type=int, default=256, help="Page size (default: 256).")
    list_parser.add_argument(
        "--with-total",
        action="store_true",
        help="Return total count alongside the list.",
    )

    upload_pkg_parser = subparsers.add_parser("upload-pkg", help="Upload a .difypkg plugin package.")
    upload_pkg_parser.add_argument("--tenant", required=True, help="Tenant ID.")
    upload_pkg_parser.add_argument("--file", required=True, help="Path to the .difypkg file.")
    upload_pkg_parser.add_argument(
        "--verify-signature",
        action="store_true",
        help="Ask the daemon to verify the package signature.",
    )

    upload_bundle_parser = subparsers.add_parser("upload-bundle", help="Upload a bundle of plugins.")
    upload_bundle_parser.add_argument("--tenant", required=True, help="Tenant ID.")
    upload_bundle_parser.add_argument("--file", required=True, help="Path to the bundle file.")
    upload_bundle_parser.add_argument(
        "--verify-signature",
        action="store_true",
        help="Ask the daemon to verify bundle signatures.",
    )

    tools_parser = subparsers.add_parser(
        "list-tools",
        help="List tool providers (or a single provider) for a tenant.",
    )
    tools_parser.add_argument("--tenant", required=True, help="Tenant ID.")
    tools_parser.add_argument(
        "--provider",
        help="Specific provider in plugin_id/provider_name or organization/plugin_name/provider_name form. If omitted, all providers are listed.",
    )

    invoke_parser = subparsers.add_parser("invoke", help="Invoke a tool.")
    invoke_parser.add_argument("--tenant", required=True, help="Tenant ID.")
    invoke_parser.add_argument("--user", required=True, help="User ID for the invocation.")
    invoke_parser.add_argument(
        "--provider",
        required=True,
        help="Tool provider in plugin_id/provider_name or organization/plugin_name/provider_name form.",
    )
    invoke_parser.add_argument("--tool", required=True, help="Tool name.")
    invoke_parser.add_argument(
        "--credentials",
        help="Credentials as a JSON string.",
    )
    invoke_parser.add_argument(
        "--credentials-file",
        help="Path to a JSON file containing credentials.",
    )
    invoke_parser.add_argument(
        "--params",
        help="Tool parameters as a JSON string.",
    )
    invoke_parser.add_argument(
        "--params-file",
        help="Path to a JSON file containing tool parameters.",
    )

    return parser


def _handle_list(args: argparse.Namespace) -> int:
    client = _build_client(args)
    if args.with_total:
        result = client.list_plugins_with_total(args.tenant, args.page, args.page_size)
        print(json.dumps(result, indent=2, default=_json_default_serializer))
        return 0

    plugins = client.list_plugins(args.tenant)
    if not plugins:
        print("No plugins found.")
        return 0

    for plugin in plugins:
        print(f"{plugin.identity.name} ({plugin.plugin_unique_identifier})")
    return 0


def _handle_upload_pkg(args: argparse.Namespace) -> int:
    client = _build_client(args)
    pkg_bytes = Path(args.file).read_bytes()
    decoded = client.upload_pkg(
        tenant_id=args.tenant,
        pkg=pkg_bytes,
        verify_signature=args.verify_signature,
    )
    print(f"Uploaded plugin: {decoded.unique_identifier}")
    return 0


def _handle_upload_bundle(args: argparse.Namespace) -> int:
    client = _build_client(args)
    bundle_bytes = Path(args.file).read_bytes()
    dependencies = client.upload_bundle(
        tenant_id=args.tenant,
        bundle=bundle_bytes,
        verify_signature=args.verify_signature,
    )
    print(json.dumps(dependencies, indent=2, default=_json_default_serializer))
    return 0


def _handle_list_tools(args: argparse.Namespace) -> int:
    client = _build_client(args)
    if args.provider:
        provider = client.fetch_tool_provider(args.tenant, args.provider)
        print(json.dumps(provider, indent=2, default=_json_default_serializer))
        return 0

    providers = client.fetch_tool_providers(args.tenant)
    if not providers:
        print("No tool providers found.")
        return 0

    print(json.dumps(providers, indent=2, default=_json_default_serializer))
    return 0


def _handle_invoke(args: argparse.Namespace) -> int:
    client = _build_client(args)

    credentials = _parse_json_arg(args.credentials, args.credentials_file, default={})
    parameters = _parse_json_arg(args.params, args.params_file, default={})

    response_stream = client.invoke(
        tenant_id=args.tenant,
        user_id=args.user,
        tool_provider=args.provider,
        tool_name=args.tool,
        credentials=credentials,
        tool_parameters=parameters,
    )

    for message in response_stream:
        if message.type == ToolInvokeMessage.MessageType.TEXT:
            print(message.message.text, end="", flush=True)
        elif message.type == ToolInvokeMessage.MessageType.JSON:
            print(json.dumps(message.message.data, indent=2, default=_json_default_serializer))
        else:
            print(f"[{message.type}] {message.message}")

    if sys.stdout.isatty():
        print()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        match args.command:
            case "list":
                return _handle_list(args)
            case "upload-pkg":
                return _handle_upload_pkg(args)
            case "upload-bundle":
                return _handle_upload_bundle(args)
            case "list-tools":
                return _handle_list_tools(args)
            case "invoke":
                return _handle_invoke(args)
            case _:
                parser.error(f"Unknown command: {args.command}")
    except ValueError as exc:
        parser.error(str(exc))
    except Exception as exc:  # pragma: no cover - guardrail for unexpected failures
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

