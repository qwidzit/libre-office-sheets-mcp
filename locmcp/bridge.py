"""The UNO side: connect to LibreOffice, resolve documents, sheets and ranges.

A single module-level Connection is cached. LibreOffice going away raises
DisposedException from any UNO call, so `session()` drops the cache and
reconnects once before giving up.
"""

import os
import subprocess
import sys
import time
from contextlib import contextmanager

from . import convert
from .jsonrpc import log

HOST = os.environ.get("LOCALC_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("LOCALC_MCP_PORT", "2002"))
AUTOLAUNCH = os.environ.get("LOCALC_MCP_AUTOLAUNCH", "1") not in ("0", "false", "no")
LAUNCH_TIMEOUT = float(os.environ.get("LOCALC_MCP_LAUNCH_TIMEOUT", "45"))

CALC_SERVICE = "com.sun.star.sheet.SpreadsheetDocument"

_uno = None
_uno_error = None
_connection = None
_active_doc_hint = None


class CalcError(Exception):
    """A problem the model should see and can usually act on."""


def uno_module():
    """Import pyuno lazily so the server still starts (and can explain) without it."""
    global _uno, _uno_error
    if _uno is not None:
        return _uno
    if _uno_error is not None:
        raise CalcError(_uno_error)
    try:
        import uno  # noqa: F401  (provided by LibreOffice, not pip)
        _uno = uno
        return _uno
    except ImportError as exc:
        _uno_error = (
            "Could not import the 'uno' module (%s).\n\n"
            "This server must be run by LibreOffice's own Python, which bundles the "
            "UNO bindings. On Windows that is usually:\n"
            "  C:\\Program Files\\LibreOffice\\program\\python.exe\n"
            "Point your MCP client's 'command' at that interpreter rather than a "
            "system or venv Python." % exc
        )
        raise CalcError(_uno_error)


# --- launching ---------------------------------------------------------------

def _soffice_path():
    explicit = os.environ.get("LOCALC_MCP_SOFFICE")
    if explicit and os.path.exists(explicit):
        return explicit

    exe = "soffice.exe" if os.name == "nt" else "soffice"
    # We are most likely running under LibreOffice's bundled interpreter, so
    # soffice is sitting right next to it.
    sibling = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), exe)
    if os.path.exists(sibling):
        return sibling

    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    from shutil import which
    return which(exe)


def _launch():
    path = _soffice_path()
    if not path:
        raise CalcError(
            "LibreOffice is not running with a UNO socket and soffice could not be "
            "found automatically. Start it yourself with:\n"
            '  soffice --calc --accept="socket,host=%s,port=%d;urp;"\n'
            "or set LOCALC_MCP_SOFFICE to the full path of soffice." % (HOST, PORT)
        )
    args = [
        path,
        "--calc",
        "--norestore",
        '--accept=socket,host=%s,port=%d;urp;' % (HOST, PORT),
    ]
    log("launching LibreOffice: %s" % path)
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        # Detach so LibreOffice outlives this server process.
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


def _resolve_context(uno_mod):
    local = uno_mod.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local
    )
    url = "uno:socket,host=%s,port=%d;urp;StarOffice.ComponentContext" % (HOST, PORT)
    return resolver.resolve(url)


class Connection(object):
    def __init__(self, ctx, uno_mod):
        self.ctx = ctx
        self.uno = uno_mod
        self.smgr = ctx.ServiceManager
        self.desktop = self.smgr.createInstanceWithContext(
            "com.sun.star.frame.Desktop", ctx
        )

    def create(self, service):
        return self.smgr.createInstanceWithContext(service, self.ctx)


def connect(allow_launch=True):
    """Return a live Connection, launching LibreOffice if we are allowed to."""
    global _connection
    if _connection is not None:
        return _connection

    uno_mod = uno_module()
    try:
        _connection = Connection(_resolve_context(uno_mod), uno_mod)
        return _connection
    except Exception as first_error:
        if not (allow_launch and AUTOLAUNCH):
            raise CalcError(
                "Could not reach LibreOffice on %s:%d (%s). Start it with:\n"
                '  soffice --calc --accept="socket,host=%s,port=%d;urp;"'
                % (HOST, PORT, first_error, HOST, PORT)
            )

    _launch()
    deadline = time.time() + LAUNCH_TIMEOUT
    last = None
    while time.time() < deadline:
        time.sleep(1.0)
        try:
            _connection = Connection(_resolve_context(uno_mod), uno_mod)
            log("connected to LibreOffice on %s:%d" % (HOST, PORT))
            return _connection
        except Exception as exc:
            last = exc
    raise CalcError(
        "Started LibreOffice but could not connect on %s:%d within %.0fs (%s)."
        % (HOST, PORT, LAUNCH_TIMEOUT, last)
    )


def _is_disposed(exc):
    return "DisposedException" in type(exc).__name__ or "DisposedException" in repr(exc)


def with_reconnect(fn):
    """Run fn(connection), reconnecting once if the bridge has gone stale."""
    global _connection
    try:
        return fn(connect())
    except CalcError:
        raise
    except Exception as exc:
        if not _is_disposed(exc):
            raise
        log("UNO bridge disposed; reconnecting")
        _connection = None
        return fn(connect())


# --- documents ---------------------------------------------------------------

def calc_documents(conn):
    docs = []
    enum = conn.desktop.getComponents().createEnumeration()
    while enum.hasMoreElements():
        component = enum.nextElement()
        try:
            if component.supportsService(CALC_SERVICE):
                docs.append(component)
        except Exception:
            continue
    return docs


def doc_path(doc):
    url = getattr(doc, "URL", "") or ""
    if not url:
        return ""
    try:
        return uno_module().fileUrlToSystemPath(url)
    except Exception:
        return url


def doc_label(doc):
    path = doc_path(doc)
    if path:
        return os.path.basename(path)
    try:
        return doc.getTitle()
    except Exception:
        return "Untitled"


def set_active_document(doc):
    global _active_doc_hint
    _active_doc_hint = getattr(doc, "URL", "") or doc_label(doc)


def resolve_document(conn, selector=None):
    """Pick a document by name/path substring/index, else fall back sensibly."""
    docs = calc_documents(conn)
    if not docs:
        raise CalcError(
            "No spreadsheet is open in LibreOffice. Use open_document to open an "
            "existing file or create a new one."
        )

    if selector not in (None, ""):
        selector = str(selector).strip()
        if selector.isdigit():
            index = int(selector)
            if 0 <= index < len(docs):
                return docs[index]
            raise CalcError(
                "Document index %d is out of range (%d open)." % (index, len(docs))
            )
        needle = selector.lower()
        matches = [
            d for d in docs
            if needle in doc_label(d).lower() or needle in doc_path(d).lower()
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise CalcError(
                "No open document matches %r. Open documents: %s"
                % (selector, ", ".join(doc_label(d) for d in docs))
            )
        raise CalcError(
            "%r matches several documents: %s"
            % (selector, ", ".join(doc_label(d) for d in matches))
        )

    if len(docs) == 1:
        return docs[0]

    if _active_doc_hint:
        for d in docs:
            if (getattr(d, "URL", "") or doc_label(d)) == _active_doc_hint:
                return d

    try:
        current = conn.desktop.getCurrentComponent()
        if current is not None and current.supportsService(CALC_SERVICE):
            return current
    except Exception:
        pass
    return docs[0]


# --- sheets ------------------------------------------------------------------

def resolve_sheet(doc, selector=None):
    sheets = doc.Sheets
    names = list(sheets.ElementNames)
    if selector in (None, ""):
        try:
            active = doc.CurrentController.getActiveSheet()
            if active is not None:
                return active
        except Exception:
            pass
        return sheets.getByIndex(0)

    selector = str(selector).strip()
    if sheets.hasByName(selector):
        return sheets.getByName(selector)
    if selector.isdigit():
        index = int(selector)
        if 0 <= index < len(names):
            return sheets.getByIndex(index)
        raise CalcError("Sheet index %d is out of range (%d sheets)." % (index, len(names)))
    lowered = {n.lower(): n for n in names}
    if selector.lower() in lowered:
        return sheets.getByName(lowered[selector.lower()])
    raise CalcError("No sheet named %r. Sheets: %s" % (selector, ", ".join(names)))


def used_range(sheet):
    """The sheet's occupied rectangle, as a RangeSpec. Empty sheets give A1:A1."""
    cursor = sheet.createCursor()
    cursor.gotoStartOfUsedArea(False)
    cursor.gotoEndOfUsedArea(True)
    addr = cursor.RangeAddress
    return convert.RangeSpec(addr.StartColumn, addr.StartRow, addr.EndColumn, addr.EndRow)


def named_range_spec(doc, name):
    """Resolve a document-level named range to (sheet, RangeSpec), or None."""
    try:
        ranges = doc.NamedRanges
    except Exception:
        return None
    if not ranges.hasByName(name):
        return None
    cells = ranges.getByName(name).getReferredCells()
    addr = cells.RangeAddress
    sheet = doc.Sheets.getByIndex(addr.Sheet)
    return sheet, convert.RangeSpec(
        addr.StartColumn, addr.StartRow, addr.EndColumn, addr.EndRow
    )


def resolve_range(doc, range_ref=None, sheet_selector=None, default_to_used=True):
    """Turn a user-supplied reference into (sheet, RangeSpec).

    Handles a 'Sheet.' prefix on the reference itself, named ranges, whole
    column/row references, and a missing reference meaning "the used area".
    """
    if range_ref in (None, ""):
        sheet = resolve_sheet(doc, sheet_selector)
        if not default_to_used:
            raise CalcError("A range reference is required for this operation.")
        return sheet, used_range(sheet)

    range_ref = str(range_ref).strip()
    prefix, tail = convert.split_sheet(range_ref)
    if prefix is not None:
        sheet = resolve_sheet(doc, prefix)
    else:
        named = named_range_spec(doc, range_ref)
        if named is not None:
            return named
        sheet = resolve_sheet(doc, sheet_selector)
    return sheet, convert.parse_range(tail, used_range(sheet))


def cell_range(sheet, spec):
    return sheet.getCellRangeByPosition(
        spec.start_col, spec.start_row, spec.end_col, spec.end_row
    )


def null_date(doc):
    try:
        nd = doc.getPropertyValue("NullDate")
        return (nd.Year, nd.Month, nd.Day)
    except Exception:
        return (1899, 12, 30)


# --- undo --------------------------------------------------------------------

@contextmanager
def undo_step(doc, title):
    """Marks one logical operation, and deliberately does NOT open a UNO undo context.

    LibreOffice records its own undo action for every change made through the
    API, and a bulk range write counts as a single entry, so Ctrl+Z reverses a
    whole written block on its own. Wrapping those calls in
    enterUndoContext/leaveUndoContext produces a tidier-looking undo list but
    breaks it outright: undo() pops the composite entry and returns cleanly
    while the contained changes stay applied.

    One LibreOffice limitation survives (measured on 24.2, undo via both
    XUndoManager and the .uno:Undo dispatch): setDataArray/setFormulaArray into
    cells that were *empty* beforehand cannot be undone -- the entry is consumed
    but the new content remains. Overwriting cells that already held something
    undoes correctly, as do single-cell writes, clears, formatting, row and
    column edits, sorting, replace and every sheet operation. So the case that
    does not undo is also the case where nothing was lost.
    """
    log("operation: %s" % title)
    yield


def make_struct(name, **fields):
    struct = uno_module().createUnoStruct(name)
    for key, value in fields.items():
        setattr(struct, key, value)
    return struct


def typed_any(type_name, value):
    """Wrap a sequence in an explicitly typed Any.

    A bare Python tuple marshals as sequence<any>, which Calc silently ignores
    for things like a sort descriptor's SortFields. The element type has to be
    spelled out.
    """
    return uno_module().Any(type_name, value)


def to_file_url(path):
    return uno_module().systemPathToFileUrl(os.path.abspath(os.path.expanduser(path)))


def prop(name, value):
    return make_struct("com.sun.star.beans.PropertyValue", Name=name, Value=value)
