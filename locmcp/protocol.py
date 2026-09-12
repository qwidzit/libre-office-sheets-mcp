"""The MCP layer: initialize handshake, tools/list, tools/call."""

import traceback

from . import __version__, registry
from .jsonrpc import INVALID_PARAMS, METHOD_NOT_FOUND, RpcError, log

# Revisions reachable through the `initialize` handshake, oldest to newest.
HANDSHAKE_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
PREFERRED_VERSION = "2025-06-18"

SERVER_INFO = {
    "name": "libreoffice-calc",
    "title": "LibreOffice Calc",
    "version": __version__,
}


def _initialize(params):
    requested = params.get("protocolVersion")
    version = requested if requested in HANDSHAKE_VERSIONS else PREFERRED_VERSION
    client = (params.get("clientInfo") or {}).get("name", "unknown client")
    log("initialize from %s (protocol %s)" % (client, version))
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": SERVER_INFO,
        "instructions": (
            "Drives a live LibreOffice Calc instance over the UNO bridge. Call "
            "calc_status first to see which documents and sheets are open and what "
            "their used ranges are, then read before you write. Ranges accept A1 "
            "notation ('B2', 'A1:D20', 'Sheet2.A1:C9', 'A:C' for whole columns) and "
            "named ranges. Your changes go onto LibreOffice's own undo stack, so the user "
            "can reverse them with Ctrl+Z; the one exception is a bulk write into "
            "cells that were empty, which LibreOffice cannot undo. Changes are live "
            "in the open window but stay unsaved on disk until you call "
            "save_document, so save before doing anything sweeping."
        ),
    }


def _tools_list(params):
    tools = []
    for entry in registry.all_tools():
        tools.append(
            {
                "name": entry["name"],
                "description": entry["description"],
                "inputSchema": entry["inputSchema"],
                "annotations": entry["annotations"],
            }
        )
    return {"tools": tools}


def _tools_call(params):
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str):
        raise RpcError(INVALID_PARAMS, "tools/call requires a string 'name'")
    entry = registry.get(name)
    if entry is None:
        raise RpcError(METHOD_NOT_FOUND, "unknown tool: %s" % name)
    if not isinstance(arguments, dict):
        raise RpcError(INVALID_PARAMS, "'arguments' must be an object")

    try:
        text = entry["handler"](arguments)
        is_error = False
    except Exception as exc:
        # Tool-level failures belong in the result so the model can self-correct;
        # only protocol-level problems become JSON-RPC errors.
        log("tool %s failed: %s" % (name, traceback.format_exc()))
        text = "%s: %s" % (type(exc).__name__, exc)
        is_error = True

    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _ping(params):
    return {}


def _noop(params):
    return None


HANDLERS = {
    "initialize": _initialize,
    "ping": _ping,
    "tools/list": _tools_list,
    "tools/call": _tools_call,
    "notifications/initialized": _noop,
    "notifications/cancelled": _noop,
    "notifications/progress": _noop,
}
