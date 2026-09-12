"""The MCP layer: initialize handshake, tools/list, tools/call."""

import os
import threading
import traceback

from . import __version__, registry
from .jsonrpc import INVALID_PARAMS, METHOD_NOT_FOUND, RpcError, log

# Revisions reachable through the `initialize` handshake, oldest to newest.
HANDSHAKE_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
PREFERRED_VERSION = "2025-06-18"

# LibreOffice services UNO calls on its main thread, so anything modal -- a
# dialog, a cell left in edit mode -- blocks every call until it is dismissed.
# A UNO call cannot be interrupted, so run it on a worker and answer without it
# rather than leaving the client waiting on a reply that may never come.
CALL_TIMEOUT = float(os.environ.get("LOCALC_MCP_TIMEOUT", "60"))

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
        text = _call_with_timeout(entry["handler"], arguments, name)
        is_error = False
    except Exception as exc:
        # Tool-level failures belong in the result so the model can self-correct;
        # only protocol-level problems become JSON-RPC errors.
        log("tool %s failed: %s" % (name, traceback.format_exc()))
        text = "%s: %s" % (type(exc).__name__, exc)
        is_error = True

    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_with_timeout(handler, arguments, name):
    outcome = {}

    def work():
        try:
            outcome["result"] = handler(arguments)
        except BaseException as exc:  # re-raised on the calling thread
            outcome["error"] = exc

    worker = threading.Thread(target=work, name="tool-%s" % name, daemon=True)
    worker.start()
    worker.join(CALL_TIMEOUT)
    if worker.is_alive():
        raise TimeoutError(
            "LibreOffice did not respond within %.0f seconds. It is almost "
            "always showing something modal that has to be dealt with in the "
            "LibreOffice window -- a dialog box, or a cell still in edit mode. "
            "Dismiss it and try again. (Raise LOCALC_MCP_TIMEOUT if the "
            "operation is genuinely this slow.)" % CALL_TIMEOUT)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


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
