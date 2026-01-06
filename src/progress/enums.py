"""Enumeration type definitions"""

from enum import Enum


class Protocol(Enum):
    """Git protocol types"""

    HTTPS = "https"
    SSH = "ssh"
