from pydantic import BaseModel, Field

class I18nObject(BaseModel):
    en_US: str = Field(..., description="English")
    zh_Hans: str | None = Field(default=None, description="Chinese")
