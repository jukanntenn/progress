#!/usr/bin/env python
"""Web server startup script for local development."""

import sys
from pathlib import Path

from progress.config import Config
from progress.web import create_app


def main():
    """Start the web server."""
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.toml"

    if not Path(config_path).exists():
        print(f"Configuration file not found: {config_path}")
        sys.exit(1)

    config = Config.load_from_file(config_path)

    if not config.web.enabled:
        print("Web service is disabled in configuration.")
        print("Please set [web] enabled = true in config.toml")
        sys.exit(1)

    app = create_app(config)

    host = config.web.host
    port = config.web.port

    print(f"Starting web service on http://{host}:{port}")
    print("Press Ctrl+C to stop")

    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
