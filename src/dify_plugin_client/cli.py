from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dify_plugin_client import DifyPluginClient, PluginConfig
from dify_plugin_client.entities.plugin import PluginInstallationSource
from dify_plugin_client.entities.tools import ToolInvokeMessage
from dify_plugin_client.utils import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_KEY,
    DEFAULT_URL,
    build_permission_lookup,
    json_default_serializer,
    load_settings,
    parse_json_arg,
    plugin_permission_summary,
    resolve_client_config,
)
TENANT_REQUIRED_COMMANDS = {
    "list",
    "upload-pkg",
    "upload-bundle",
    "list-tools",
    "invoke",
    "install",
}


def _resolve_settings(args: argparse.Namespace, parser: argparse.ArgumentParser) -> argparse.Namespace:
    config_path = Path(getattr(args, "config", DEFAULT_CONFIG_PATH))
    settings = load_settings(config_path)

    env_settings = {
        "tenant": os.getenv("DIFY_PLUGIN_TENANT_ID") or os.getenv("DIFY_PLUGIN_TENANT"),
    }

    client_config = resolve_client_config(
        url=args.url,
        key=args.key,
        timeout=args.timeout,
        config_path=config_path,
        env=os.environ,
    )

    args.url = client_config.url or DEFAULT_URL
    args.key = client_config.key or DEFAULT_KEY
    args.timeout = client_config.timeout

    if hasattr(args, "tenant"):
        args.tenant = args.tenant or env_settings["tenant"] or settings.get("tenant")
        if args.command in TENANT_REQUIRED_COMMANDS and not args.tenant:
            parser.error(
                "Tenant ID is required. Provide --tenant, set DIFY_PLUGIN_TENANT_ID, or set tenant in the config file."
            )

    return args


def _build_client(args: argparse.Namespace) -> DifyPluginClient:
    return DifyPluginClient(
        resolve_client_config(
            url=args.url,
            key=args.key,
            timeout=args.timeout,
            config_path=getattr(args, "config", DEFAULT_CONFIG_PATH),
            env=os.environ,
        )
    )


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to config file with defaults (default: {DEFAULT_CONFIG_PATH}).",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Plugin daemon URL (env: DIFY_PLUGIN_DAEMON_URL).",
    )
    parser.add_argument(
        "--key",
        default=None,
        help="Plugin daemon API key (env: DIFY_PLUGIN_DAEMON_KEY).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Request timeout in seconds (env: DIFY_PLUGIN_DAEMON_TIMEOUT).",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dify-plugin-client",
        description="Interact with a Dify plugin daemon from the command line.",
    )
    _add_common_arguments(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List installed plugins for a tenant.")
    list_parser.add_argument("--tenant", help="Tenant ID.")
    list_parser.add_argument("--page", type=int, default=1, help="Page number (default: 1).")
    list_parser.add_argument("--page-size", type=int, default=256, help="Page size (default: 256).")
    list_parser.add_argument(
        "--with-total",
        action="store_true",
        help="Return total count alongside the list.",
    )

    upload_pkg_parser = subparsers.add_parser("upload-pkg", help="Upload a .difypkg plugin package.")
    upload_pkg_parser.add_argument("--tenant", help="Tenant ID.")
    upload_pkg_parser.add_argument("--file", required=True, help="Path to the .difypkg file.")
    upload_pkg_parser.add_argument(
        "--verify-signature",
        action="store_true",
        help="Ask the daemon to verify the package signature.",
    )

    upload_bundle_parser = subparsers.add_parser("upload-bundle", help="Upload a bundle of plugins.")
    upload_bundle_parser.add_argument("--tenant", help="Tenant ID.")
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
    tools_parser.add_argument("--tenant", help="Tenant ID.")
    tools_parser.add_argument(
        "--provider",
        help="Specific provider in plugin_id/provider_name or organization/plugin_name/provider_name form. If omitted, all providers are listed.",
    )

    invoke_parser = subparsers.add_parser("invoke", help="Invoke a tool.")
    invoke_parser.add_argument("--tenant", help="Tenant ID.")
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

    install_parser = subparsers.add_parser(
        "install",
        help="Install plugins from identifiers or upload-and-install a .difypkg.",
    )
    install_parser.add_argument("--tenant", help="Tenant ID.")
    install_parser.add_argument(
        "--identifier",
        action="append",
        help="Plugin unique identifier to install. Can be provided multiple times.",
    )
    install_parser.add_argument(
        "--file",
        help="Path to a .difypkg file to upload and install.",
    )
    install_parser.add_argument(
        "--source",
        choices=[source.value for source in PluginInstallationSource],
        default=PluginInstallationSource.Package.value,
        help="Installation source when using identifiers (default: Package).",
    )
    install_parser.add_argument(
        "--meta",
        help="Metadata JSON applied to each identifier during install.",
    )
    install_parser.add_argument(
        "--meta-file",
        help="Path to a JSON file containing metadata applied to each identifier during install.",
    )
    install_parser.add_argument(
        "--verify-signature",
        action="store_true",
        help="Verify package signature when using --file.",
    )

    return parser


def _handle_list(args: argparse.Namespace) -> int:
    client = _build_client(args)
    if args.with_total:
        result = client.list_plugins_with_total(args.tenant, args.page, args.page_size)
        print(json.dumps(result, indent=2, default=json_default_serializer))
        return 0

    plugins = client.list_plugins(args.tenant)
    if not plugins:
        print("No plugins found.")
        return 0

    for plugin in plugins:
        permission_summary = plugin_permission_summary(plugin)
        print(f"{plugin.name} ({plugin.plugin_unique_identifier}) - permissions: {permission_summary}")
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
    print(json.dumps(dependencies, indent=2, default=json_default_serializer))
    return 0


def _handle_install(args: argparse.Namespace) -> int:
    client = _build_client(args)

    identifiers: list[str] = []
    metas: list[dict[str, Any]] = []
    meta = parse_json_arg(args.meta, args.meta_file, default={})
    if not isinstance(meta, dict):
        raise ValueError("--meta must be a JSON object")

    if args.identifier:
        identifiers.extend(args.identifier)

    if args.file:
        pkg_bytes = Path(args.file).read_bytes()
        decoded = client.upload_pkg(
            tenant_id=args.tenant,
            pkg=pkg_bytes,
            verify_signature=args.verify_signature,
        )
        identifiers.append(decoded.unique_identifier)

    if not identifiers:
        raise ValueError("Provide at least one --identifier or --file to install.")

    metas = [meta for _ in identifiers]
    source = PluginInstallationSource.Package if args.file else PluginInstallationSource(args.source)

    response = client.install_from_identifiers(
        tenant_id=args.tenant,
        identifiers=identifiers,
        source=source,
        metas=metas,
    )

    print(
        json.dumps(
            {
                "task_id": response.task_id,
                "all_installed": response.all_installed,
                "identifiers": identifiers,
            },
            indent=2,
            default=json_default_serializer,
        )
    )

    return 0


def _handle_list_tools(args: argparse.Namespace) -> int:
    client = _build_client(args)
    permission_lookup = build_permission_lookup(client, args.tenant)

    if args.provider:
        provider = client.fetch_tool_provider(args.tenant, args.provider)
        provider_dict = provider.model_dump()
        provider_dict["permission_summary"] = permission_lookup.get(provider.plugin_unique_identifier, "unknown")
        print(json.dumps(provider_dict, indent=2, default=json_default_serializer))
        return 0

    providers = client.fetch_tool_providers(args.tenant)
    if not providers:
        print("No tool providers found.")
        return 0

    enriched = []
    for provider in providers:
        provider_dict = provider.model_dump()
        provider_dict["permission_summary"] = permission_lookup.get(provider.plugin_unique_identifier, "unknown")
        enriched.append(provider_dict)

    print(json.dumps(enriched, indent=2, default=json_default_serializer))
    return 0


def _handle_invoke(args: argparse.Namespace) -> int:
    client = _build_client(args)

    credentials = parse_json_arg(args.credentials, args.credentials_file, default={})
    parameters = parse_json_arg(args.params, args.params_file, default={})

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
            payload = message.message.normalized if message.message else {}
            print(json.dumps(payload, indent=2, default=json_default_serializer))
        else:
            print(f"[{message.type}] {message.message}")

    if sys.stdout.isatty():
        print()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args = _resolve_settings(args, parser)

    try:
        match args.command:
            case "list":
                return _handle_list(args)
            case "upload-pkg":
                return _handle_upload_pkg(args)
            case "upload-bundle":
                return _handle_upload_bundle(args)
            case "install":
                return _handle_install(args)
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

