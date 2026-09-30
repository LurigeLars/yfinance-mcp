"""Read-only Yahoo Finance options data exposed through MCP."""

__version__ = "0.5.0"


def main() -> None:
    """Run the MCP server over stdio."""
    from .server import mcp

    mcp.run()
