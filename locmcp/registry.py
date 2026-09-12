"""Tool registry and small JSON Schema helpers."""

_TOOLS = {}
_ORDER = []


def tool(name, description, properties=None, required=(), title=None, read_only=False):
    """Register a tool. The decorated function takes (args: dict) and returns str."""

    def decorate(fn):
        schema = {
            "type": "object",
            "properties": properties or {},
            "required": list(required),
            "additionalProperties": False,
        }
        entry = {
            "name": name,
            "description": description,
            "inputSchema": schema,
            "handler": fn,
            "annotations": {
                "title": title or name,
                "readOnlyHint": read_only,
                "destructiveHint": not read_only,
            },
        }
        _TOOLS[name] = entry
        _ORDER.append(name)
        return fn

    return decorate


def all_tools():
    return [_TOOLS[name] for name in _ORDER]


def get(name):
    return _TOOLS.get(name)


# --- schema shorthands -------------------------------------------------------

def string(description, **kw):
    return dict(type="string", description=description, **kw)


def integer(description, **kw):
    return dict(type="integer", description=description, **kw)


def number(description, **kw):
    return dict(type="number", description=description, **kw)


def boolean(description, **kw):
    return dict(type="boolean", description=description, **kw)


def enum(description, values, **kw):
    return dict(type="string", description=description, enum=list(values), **kw)


def array(description, items, **kw):
    return dict(type="array", description=description, items=items, **kw)


DOCUMENT = string(
    "Which open document to act on: a filename, a substring of its path, or its "
    "index from calc_status. Defaults to the active document (or the only open one)."
)
SHEET = string(
    "Sheet name, or a 0-based index as a string. Defaults to the active sheet."
)
