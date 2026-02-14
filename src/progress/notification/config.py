from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ConsoleChannelConfig(BaseModel):
    type: Literal["console"] = "console"
    enabled: bool = True


class FeishuChannelConfig(BaseModel):
    type: Literal["feishu"] = "feishu"
    enabled: bool = True

    webhook_url: HttpUrl
    timeout: int = Field(default=30, ge=1)


class EmailChannelConfig(BaseModel):
    type: Literal["email"] = "email"
    enabled: bool = True

    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    user: str = ""
    password: str = ""
    from_addr: str = "progress@example.com"
    recipient: list[str] = Field(default_factory=list)
    starttls: bool = False
    ssl: bool = False

    @model_validator(mode="after")
    def validate_email_config(self) -> "EmailChannelConfig":
        if not self.enabled:
            return self

        missing_fields = []
        if not self.host:
            missing_fields.append("host")
        if not self.recipient:
            missing_fields.append("recipient")

        if missing_fields:
            raise ValueError(
                f"Missing required fields for email notification: {', '.join(missing_fields)}"
            )

        return self


NotificationChannelConfig = Annotated[
    Union[ConsoleChannelConfig, FeishuChannelConfig, EmailChannelConfig],
    Field(discriminator="type"),
]


class NotificationConfig(BaseModel):
    channels: list[NotificationChannelConfig] = Field(default_factory=list)
