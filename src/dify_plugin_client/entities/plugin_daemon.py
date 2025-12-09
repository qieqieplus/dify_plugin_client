import enum
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from .._compat import StrEnum
from .parameters import PluginParameterOption
from .plugin import PluginDeclaration, PluginEntity
from .tools import ToolProviderEntity


T = TypeVar("T", bound=(BaseModel | dict | list | bool | str))


class PluginDaemonBasicResponse(BaseModel, Generic[T]):
    """
    Basic response from plugin daemon.
    """

    code: int
    message: str
    data: T | None = None


class InstallPluginMessage(BaseModel):
    """
    Message for installing a plugin.
    """

    class Event(StrEnum):
        Info = "info"
        Done = "done"
        Error = "error"

    event: Event
    data: str


class PluginToolProviderEntity(BaseModel):
    provider: str
    plugin_unique_identifier: str
    plugin_id: str
    declaration: ToolProviderEntity

    def __str__(self):
        return self.declaration.identity.name


class PluginBasicBooleanResponse(BaseModel):
    """
    Basic boolean response from plugin daemon.
    """

    result: bool
    credentials: dict | None = None


class PluginDaemonError(BaseModel):
    """
    Error from plugin daemon.
    """

    error_type: str
    message: str


class PluginInstallTaskStatus(StrEnum):
    Pending = "pending"
    Running = "running"
    Success = "success"
    Failed = "failed"


class PluginInstallTaskPluginStatus(BaseModel):
    plugin_unique_identifier: str = Field(description="The plugin unique identifier of the install task.")
    plugin_id: str = Field(description="The plugin ID of the install task.")
    status: PluginInstallTaskStatus = Field(description="The status of the install task.")
    message: str = Field(description="The message of the install task.")
    icon: str = Field(description="The icon of the plugin.")


class PluginInstallTask(BaseModel):
    status: PluginInstallTaskStatus = Field(description="The status of the install task.")
    total_plugins: int = Field(description="The total number of plugins to be installed.")
    completed_plugins: int = Field(description="The number of plugins that have been installed.")
    plugins: list[PluginInstallTaskPluginStatus] = Field(description="The status of the plugins.")


class PluginInstallTaskStartResponse(BaseModel):
    all_installed: bool = Field(description="Whether all plugins are installed.")
    task_id: str = Field(description="The ID of the install task.")


class PluginVerification(BaseModel):
    """
    Verification of the plugin.
    """

    class AuthorizedCategory(StrEnum):
        Langgenius = "langgenius"
        Partner = "partner"
        Community = "community"

    authorized_category: AuthorizedCategory = Field(description="The authorized category of the plugin.")


class PluginDecodeResponse(BaseModel):
    unique_identifier: str = Field(description="The unique identifier of the plugin.")
    manifest: PluginDeclaration
    verification: PluginVerification | None = Field(default=None, description="Basic verification information")


class PluginListResponse(BaseModel):
    list: list[PluginEntity]
    total: int


class PluginDynamicSelectOptionsResponse(BaseModel):
    options: Sequence[PluginParameterOption] = Field(description="The options of the dynamic select.")


class CredentialType(StrEnum):
    API_KEY = "api-key"
    OAUTH2 = "oauth2"
    UNAUTHORIZED = "unauthorized"

    def get_name(self):
        if self == CredentialType.API_KEY:
            return "API KEY"
        elif self == CredentialType.OAUTH2:
            return "AUTH"
        elif self == CredentialType.UNAUTHORIZED:
            return "UNAUTHORIZED"
        else:
            return self.value.replace("-", " ").upper()

    def is_editable(self):
        return self == CredentialType.API_KEY

    def is_validate_allowed(self):
        return self == CredentialType.API_KEY

    @classmethod
    def values(cls):
        return [item.value for item in cls]

    @classmethod
    def of(cls, credential_type: str) -> "CredentialType":
        type_name = credential_type.lower()
        if type_name in {"api-key", "api_key"}:
            return cls.API_KEY
        elif type_name in {"oauth2", "oauth"}:
            return cls.OAUTH2
        elif type_name == "unauthorized":
            return cls.UNAUTHORIZED
        else:
            raise ValueError(f"Invalid credential type: {credential_type}")


class PluginReadmeResponse(BaseModel):
    content: str = Field(description="The readme of the plugin.")
    language: str = Field(description="The language of the readme.")
