#!/usr/bin/env python3
"""Exercise the MCP wire protocol against server.py without needing LibreOffice.

Points the server at a dead port with auto-launch off, so the connection failure
is deterministic whether or not LibreOffice happens to be running."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from locmcp.bridge import find_interpreter  # noqa: E402


def main():
    proc = subprocess.Popen(
        [find_interpreter(), os.path.join(ROOT, "server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, env=dict(os.environ, LOCALC_MCP_AUTOLAUNCH="0", LOCALC_MCP_PORT="2999"),
    )

    def call(method, params=None, request_id=None):
        message = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            message["id"] = request_id
        if params is not None:
            message["params"] = params
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        if request_id is None:
            return None
        line = proc.stdout.readline()
        assert line, "server closed the stream"
        return json.loads(line)

    failures = []

    def check(label, condition, detail=""):
        print("%s %s%s" % ("PASS" if condition else "FAIL", label, (" -- " + detail) if detail and not condition else ""))
        if not condition:
            failures.append(label)

    init = call("initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "smoke", "version": "0"},
    }, 1)
    result = init.get("result", {})
    check("initialize returns a result", "result" in init, json.dumps(init))
    check("protocolVersion echoed", result.get("protocolVersion") == "2025-06-18", str(result))
    check("declares tools capability", "tools" in result.get("capabilities", {}))
    check("serverInfo has name+version",
          bool(result.get("serverInfo", {}).get("name")) and bool(result.get("serverInfo", {}).get("version")))

    # An unknown protocol version must be answered with one we do support.
    init2 = call("initialize", {"protocolVersion": "1999-01-01", "capabilities": {},
                                "clientInfo": {"name": "smoke", "version": "0"}}, 2)
    check("unknown protocol falls back",
          init2["result"]["protocolVersion"] in ("2025-06-18", "2025-11-25"),
          str(init2))

    call("notifications/initialized")

    listed = call("tools/list", {}, 3)
    tools = listed.get("result", {}).get("tools", [])
    check("tools/list returns tools", len(tools) >= 15, "got %d" % len(tools))
    for entry in tools:
        schema = entry.get("inputSchema", {})
        ok = (
            isinstance(entry.get("name"), str)
            and isinstance(entry.get("description"), str)
            and schema.get("type") == "object"
            and isinstance(schema.get("properties"), dict)
        )
        if not ok:
            check("tool %s has a valid definition" % entry.get("name"), False, json.dumps(entry))
    check("every tool definition is well formed", not failures or all(not f.startswith("tool ") for f in failures))

    ping = call("ping", {}, 4)
    check("ping answers", ping.get("result") == {}, str(ping))

    unknown = call("does/not/exist", {}, 5)
    check("unknown method -> -32601", unknown.get("error", {}).get("code") == -32601, str(unknown))

    missing = call("tools/call", {"name": "no_such_tool", "arguments": {}}, 6)
    check("unknown tool -> -32601", missing.get("error", {}).get("code") == -32601, str(missing))

    # A tool failure must come back as isError, not a JSON-RPC error.
    failed = call("tools/call", {"name": "calc_status", "arguments": {}}, 7)
    res = failed.get("result", {})
    check("tool failure is a result with isError", res.get("isError") is True, str(failed))
    check("tool failure carries text content",
          res.get("content", [{}])[0].get("type") == "text" and bool(res["content"][0].get("text")),
          str(res))
    check("failure explains how to reach LibreOffice",
          "accept" in res.get("content", [{}])[0].get("text", "").lower(), str(res))

    # Notifications must not produce a response; prove the stream is still aligned.
    call("notifications/cancelled", {"requestId": 1})
    after = call("ping", {}, 8)
    check("stream stays aligned after a notification", after.get("id") == 8, str(after))

    proc.stdin.write("{not json\n")
    proc.stdin.flush()
    line = json.loads(proc.stdout.readline())
    check("malformed line -> -32700", line.get("error", {}).get("code") == -32700, str(line))

    proc.stdin.close()
    proc.wait(timeout=10)

    # Reading a property off a UNO object cannot rely on getattr's default:
    # pyuno raises UnknownPropertyException, which is not AttributeError, and a
    # proxy for a closing document can refuse a property it answered before.
    from locmcp.bridge import uno_get

    class Hostile(object):
        @property
        def URL(self):
            raise RuntimeError("cannot get value URL")

    class Fine(object):
        URL = "file:///x.ods"
        Empty = None

    check("uno_get survives a property that raises", uno_get(Hostile(), "URL", "") == "")
    check("uno_get returns a real value", uno_get(Fine(), "URL", "") == "file:///x.ods")
    check("uno_get treats None as absent", uno_get(Fine(), "Empty", "fallback") == "fallback")
    check("uno_get handles a missing name", uno_get(Fine(), "Nope", "fallback") == "fallback")

    print("\n%s" % ("ALL PROTOCOL CHECKS PASSED" if not failures else "FAILURES: %s" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
