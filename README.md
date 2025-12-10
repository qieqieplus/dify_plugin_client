# Dify Plugin Client

Python client (and CLI) for talking to the Dify Plugin Daemon. It mirrors the daemon’s management and invocation APIs and performs light request/response validation so you get clear Python exceptions on failure.

## Install

```bash
pip install -e .  # or pip install .
```

## Configuration

```python
from dify_plugin_client import DifyPluginClient, PluginConfig

config = PluginConfig(
    url="http://localhost:5002",  # daemon base URL
    key="plugin-api-key",         # X-Api-Key
    timeout=30.0,                # float or httpx.Timeout
)
client = DifyPluginClient(config)
```

## API surface

All methods raise `httpx.HTTPStatusError` for HTTP failures and domain-specific errors for daemon error payloads.

### Plugin install & lifecycle
- `upload_pkg(tenant_id, pkg: bytes, verify_signature=False) -> PluginDecodeResponse`  
  Upload a `.difypkg` and get back its decoded manifest + unique identifier.
- `upload_bundle(tenant_id, bundle: bytes, verify_signature=False) -> list[PluginBundleDependency]`  
  Upload a bundle containing multiple plugins; returns declared dependencies.
- `install_from_identifiers(tenant_id, identifiers, source, metas) -> PluginInstallTaskStartResponse`  
  Start an install task from known identifiers (validates identifiers/metas length).
- `fetch_plugin_installation_task(tenant_id, task_id) -> PluginInstallTask`  
  Poll a specific install task (statuses + per-plugin messages).
- `fetch_plugin_installation_tasks(tenant_id, page, page_size) -> list[PluginInstallTask]`
- `delete_plugin_installation_task(tenant_id, task_id) -> bool`
- `delete_all_plugin_installation_task_items(tenant_id) -> bool`
- `delete_plugin_installation_task_item(tenant_id, task_id, identifier) -> bool`
- `fetch_missing_dependencies(tenant_id, plugin_unique_identifiers) -> list[MissingPluginDependency]`
- `uninstall(tenant_id, plugin_installation_id) -> bool`
- `upgrade_plugin(tenant_id, original_plugin_unique_identifier, new_plugin_unique_identifier, source, meta) -> PluginInstallTaskStartResponse`
- `fetch_plugin_installation_by_ids(tenant_id, plugin_ids) -> list[PluginInstallation]`

### Discovery & metadata
- `list_plugins(tenant_id) -> list[PluginEntity]`
- `list_plugins_with_total(tenant_id, page, page_size) -> PluginListResponse`
- `fetch_plugin_manifest(tenant_id, plugin_unique_identifier) -> PluginDeclaration`
- `decode_plugin_from_identifier(tenant_id, plugin_unique_identifier) -> PluginDecodeResponse`
- `fetch_plugin_readme(tenant_id, plugin_unique_identifier, language) -> str` (returns `""` on 404)
- `fetch_plugin_by_identifier(tenant_id, identifier) -> bool`

### Tools
- `fetch_tool_providers(tenant_id) -> list[PluginToolProviderEntity]`  
  Resolves JSON Schema `$ref`s inside tool schemas and prefixes provider names with `plugin_id/provider_name`.
- `fetch_tool_provider(tenant_id, provider: "plugin_id/provider_name" | "organization/plugin_name/provider_name") -> PluginToolProviderEntity`
- `check_tools_existence(tenant_id, provider_ids: Sequence[{"plugin_id":..., "provider_name":...}]) -> list[bool]`
- `invoke(tenant_id, user_id, tool_provider, tool_name, credentials, tool_parameters) -> Generator[ToolInvokeMessage, None, None]`  
  Streams SSE messages; parameters are auto-cast based on the tool’s declaration (string/number/boolean/file/files/select/secret handling with validation).

### Errors
- HTTP errors: `httpx.HTTPStatusError`
- Daemon error types: mapped to `PluginDaemonInnerError`, `PluginInvokeError`, `PluginDaemonBadRequestError`, `PluginDaemonNotFoundError`, `PluginUniqueIdentifierError`, `PluginPermissionDeniedError`, `PluginDaemonUnauthorizedError`, `PluginDaemonInternalServerError`, `PluginNotFoundError`.

## Example flows

### Upload and install a package
```python
from dify_plugin_client import DifyPluginClient, PluginConfig
from dify_plugin_client.entities.plugin import PluginInstallationSource
from uuid import uuid4

tenant_id = str(uuid4())
client = DifyPluginClient(PluginConfig(url="http://localhost:5002", key="plugin-api-key"))

with open("my_plugin.difypkg", "rb") as f:
    pkg_bytes = f.read()

decoded = client.upload_pkg(tenant_id=tenant_id, pkg=pkg_bytes, verify_signature=False)

task = client.install_from_identifiers(
    tenant_id=tenant_id,
    identifiers=[decoded.unique_identifier],
    source=PluginInstallationSource.Package,
    metas=[{}],
)

# simple poll loop
import time
for _ in range(60):
    t = client.fetch_plugin_installation_task(tenant_id, task.task_id)
    if t.status == "success":
        break
    if t.status == "failed":
        raise RuntimeError(f"Install failed: {[p.message for p in t.plugins]}")
    time.sleep(1)
```

### List plugins and fetch manifest/readme
```python
plugins = client.list_plugins(tenant_id)
for p in plugins:
    print(p.name, p.version)
    manifest = client.fetch_plugin_manifest(tenant_id, p.plugin_unique_identifier)
    readme = client.fetch_plugin_readme(tenant_id, p.plugin_unique_identifier, language="en")
```

### Invoke a tool (streaming)
```python
stream = client.invoke(
    tenant_id=tenant_id,
    user_id="user-123",
    tool_provider="organization/plugin_name/provider_name",
    tool_name="search",
    credentials={},  # provider-specific
    tool_parameters={"query": "hello world"},
)

for msg in stream:
    if msg.type == "text":
        print(msg.message.text, end="")
    elif msg.type == "json":
        print(msg.message.data)
```

### Check missing dependencies
```python
missing = client.fetch_missing_dependencies(tenant_id, ["plugin-a@1.0.0", "plugin-b@2.0.0"])
for dep in missing:
    print(dep.plugin_unique_identifier, dep.current_identifier)
```

### Uninstall or upgrade
```python
client.uninstall(tenant_id, plugin_installation_id="abc123")
client.upgrade_plugin(
    tenant_id,
    original_plugin_unique_identifier="plugin-a@1.0.0",
    new_plugin_unique_identifier="plugin-a@1.1.0",
    source=PluginInstallationSource.Package,
    meta={},
)
```

## CLI (optional)

After installation, the CLI mirrors key operations:
```bash
dify-plugin-client list [--tenant <tenant-id>]
dify-plugin-client upload-pkg [--tenant <tenant-id>] --file ./my_plugin.difypkg
dify-plugin-client install [--tenant <tenant-id>] --file ./my_plugin.difypkg
dify-plugin-client install [--tenant <tenant-id>] --identifier plugin@1.0.0
dify-plugin-client invoke [--tenant <tenant-id>] --user <user-id> \
  --provider plugin_id/provider_name --tool tool_name --params '{"query":"hello"}'
```

### CLI configurations

Environment defaults: `DIFY_PLUGIN_DAEMON_URL`, `DIFY_PLUGIN_DAEMON_KEY`,
`DIFY_PLUGIN_DAEMON_TIMEOUT`, `DIFY_PLUGIN_TENANT_ID`.

The CLI can also read defaults (URL, key, timeout, optional tenant) from a config
file. By default it looks for `~/.dify`, and you can point elsewhere with
`--config /path/to/file`. The file must be a JSON object:

```json
{
  "url": "http://localhost:5002",
  "key": "plugin-api-key",
  "timeout": 120,
  "tenant": "your-tenant-id"
}
```
Precedence:
CLI flags > environment variables (`DIFY_PLUGIN_DAEMON_URL`,
`DIFY_PLUGIN_DAEMON_KEY`, `DIFY_PLUGIN_DAEMON_TIMEOUT`,
`DIFY_PLUGIN_TENANT_ID`) > config file > built-in defaults.
