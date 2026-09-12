"""Newline-delimited JSON-RPC 2.0 over stdio -- the MCP stdio transport.

Deliberately stdlib-only so the server can run under LibreOffice's bundled
Python interpreter, which has `uno` but no package manager worth fighting.

The one hard rule of this transport: stdout carries protocol messages and
nothing else. `install()` hands the real stdout to the writer and repoints
`sys.stdout` at stderr, so a stray print() in tool code cannot corrupt the
stream.
"""

import io
import json
import sys
import threading

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    """An error that should be reported as a JSON-RPC error response."""

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self):
        err = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


def log(message):
    """Diagnostics go to stderr, where the MCP client shows them as server logs."""
    sys.stderr.write("[libreoffice-calc-mcp] %s\n" % (message,))
    sys.stderr.flush()


def _binary(stream):
    return getattr(stream, "buffer", stream)


def install():
    """Claim stdin/stdout for the protocol and return (reader, writer)."""
    reader = io.TextIOWrapper(_binary(sys.stdin), encoding="utf-8", newline="\n")
    writer = io.TextIOWrapper(_binary(sys.stdout), encoding="utf-8", newline="\n")
    sys.stdout = sys.stderr
    return reader, writer


class Server:
    """Reads requests from stdin, dispatches them, writes responses to stdout."""

    def __init__(self, handlers):
        self.handlers = handlers
        self._reader, self._writer = install()
        self._write_lock = threading.Lock()

    def _send(self, payload):
        with self._write_lock:
            self._writer.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._writer.flush()

    def _respond(self, request_id, result):
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _respond_error(self, request_id, error):
        self._send({"jsonrpc": "2.0", "id": request_id, "error": error.to_dict()})

    def _handle(self, message):
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if not isinstance(method, str):
            if request_id is not None:
                self._respond_error(request_id, RpcError(INVALID_REQUEST, "missing method"))
            return

        handler = self.handlers.get(method)
        if handler is None:
            # Notifications never get a response, not even for unknown methods.
            if request_id is not None:
                self._respond_error(
                    request_id, RpcError(METHOD_NOT_FOUND, "unknown method: %s" % method)
                )
            return

        try:
            result = handler(params)
        except RpcError as exc:
            if request_id is not None:
                self._respond_error(request_id, exc)
            return
        except Exception as exc:  # pragma: no cover - defensive
            log("unhandled error in %s: %r" % (method, exc))
            if request_id is not None:
                self._respond_error(request_id, RpcError(INTERNAL_ERROR, str(exc)))
            return

        if request_id is not None:
            self._respond(request_id, result if result is not None else {})

    def serve_forever(self):
        for line in self._reader:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError as exc:
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": RpcError(PARSE_ERROR, str(exc)).to_dict(),
                    }
                )
                continue
            # A batch is a list; MCP does not use them, but degrade gracefully.
            if isinstance(message, list):
                for item in message:
                    if isinstance(item, dict):
                        self._handle(item)
            elif isinstance(message, dict):
                self._handle(message)
