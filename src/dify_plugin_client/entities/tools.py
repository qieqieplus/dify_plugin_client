from enum import auto
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .._compat import StrEnum
from .common import I18nObject


class ToolLabelEnum(StrEnum):
    SEARCH = "search"
    IMAGE = "image"
    VIDEOS = "videos"
    WEATHER = "weather"
    FINANCE = "finance"
    DESIGN = "design"
    TRAVEL = "travel"
    SOCIAL = "social"
    NEWS = "news"
    MEDICAL = "medical"
    PRODUCTIVITY = "productivity"
    EDUCATION = "education"
    BUSINESS = "business"
    ENTERTAINMENT = "entertainment"
    UTILITIES = "utilities"
    RAG = "rag"
    OTHER = "other"


class ToolProviderIdentity(BaseModel):
    author: str = Field(..., description="The author of the tool")
    name: str = Field(..., description="The name of the tool")
    description: I18nObject = Field(..., description="The description of the tool")
    icon: str = Field(..., description="The icon of the tool")
    label: I18nObject = Field(..., description="The label of the tool")
    tags: list[ToolLabelEnum] | None = Field(
        default_factory=list,
        description="The tags of the tool",
    )


class ToolIdentity(BaseModel):
    author: str = Field(..., description="The author of the tool")
    name: str = Field(..., description="The name of the tool")
    label: I18nObject = Field(..., description="The label of the tool")
    provider: str = Field(..., description="The provider of the tool")
    icon: str | None = None


class ToolDescription(BaseModel):
    human: I18nObject = Field(..., description="The description presented to the user")
    llm: str = Field(..., description="The description presented to the LLM")


class ToolParameter(BaseModel):
    class ToolParameterType(StrEnum):
        STRING = "string"
        TEXT_INPUT = "text-input"
        NUMBER = "number"
        BOOLEAN = "boolean"
        SELECT = "select"
        DYNAMIC_SELECT = "dynamic-select"
        APP_SELECTOR = "app-selector"
        MODEL_SELECTOR = "model-selector"
        TOOLS_SELECTOR = "array[tools]"
        ANY = "any"
        OBJECT = "object"
        CHECKBOX = "checkbox"
        SECRET_INPUT = "secret-input"
        FILE = "file"
        FILES = "files"
        ARRAY = "array"

    class ToolParameterForm(StrEnum):
        SCHEMA = "schema"
        FORM = "form"
        LLM = "llm"

    name: str = Field(..., description="The name of the parameter")
    label: I18nObject = Field(..., description="The label of the parameter")
    type: ToolParameterType = Field(..., description="The type of the parameter")
    required: bool = Field(..., description="Whether the parameter is required")
    form: ToolParameterForm = Field(..., description="The form of the parameter")
    llm_description: str | None = None
    options: list[Any] | None = None


class ToolEntity(BaseModel):
    identity: ToolIdentity
    parameters: list[ToolParameter] = Field(default_factory=list)
    description: ToolDescription | None = None


class ToolProviderEntity(BaseModel):
    identity: ToolProviderIdentity
    tools: list[ToolEntity] = Field(default_factory=list)


class ToolInvokeMessage(BaseModel):
    class TextMessage(BaseModel):
        text: str

    class JsonMessage(BaseModel):
        model_config = ConfigDict(populate_by_name=True, extra="allow")

        # Some daemon versions emit `json`, others `json_object`; normalize to `data`.
        data: dict | None = Field(default=None, alias="json")
        json_object: dict | None = Field(default=None, alias="json_object")

        def model_post_init(self, __context):
            # Coalesce legacy field names into `data` so downstream code keeps working.
            if self.data is None and self.json_object is not None:
                self.data = self.json_object

        @staticmethod
        def _coalesce(data: dict | None, json_object: dict | None) -> dict:
            if data is not None:
                return data
            if json_object is not None:
                return json_object
            return {}

        @property
        def normalized(self) -> dict:
            return self._coalesce(self.data, self.json_object)

        def __getattr__(self, name: str):
            # Preserve existing `message.data` usage for backwards compatibility.
            if name == "data":
                return self._coalesce(self.__dict__.get("data"), self.__dict__.get("json_object"))
            raise AttributeError(name)

    class BlobMessage(BaseModel):
        blob: bytes

    class MessageType(StrEnum):
        TEXT = auto()
        JSON = auto()
        BLOB = auto()

    type: MessageType = MessageType.TEXT
    message: JsonMessage | TextMessage | BlobMessage | None
    meta: dict[str, Any] | None = None
