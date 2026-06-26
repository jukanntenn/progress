from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ConsoleChannelConfig(BaseModel):
    type: Literal["console"] = "console"
    enabled: bool = True


class FeishuChannelConfig(BaseModel):
    type: Literal["feishu"] = "feishu"
    enabled: bool = True

    webhook_url: HttpUrl = Field(
        description="Webhook URL from the Feishu bot configuration.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    timeout: int = Field(
        default=30, ge=1, description="HTTP request timeout in seconds."
    )


class EmailChannelConfig(BaseModel):
    type: Literal["email"] = "email"
    enabled: bool = True

    host: str = Field(default="", description="SMTP server hostname.")
    port: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP server port (587 for STARTTLS, 465 for SSL).",
    )
    user: str = Field(default="", description="SMTP authentication username.")
    password: str = Field(
        default="",
        description="SMTP authentication password or app-specific password.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    from_addr: str = Field(
        default="progress@example.com", description="Sender email address."
    )
    recipient: list[str] = Field(
        default_factory=list, description="Recipient email addresses."
    )
    starttls: bool = Field(
        default=False, description="Use STARTTLS (typically with port 587)."
    )
    ssl: bool = Field(
        default=False, description="Use SSL/TLS (typically with port 465)."
    )

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
