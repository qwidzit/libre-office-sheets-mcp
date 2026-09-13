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

def interpreter_dirs():
    """Directories worth searching, derived from the running interpreter.

    LibreOffice's Windows python.exe is a wrapper: the real interpreter lives in
    program/python-core-<version>/, and sys.executable does not reliably name a
    runnable file there. So take the parent of sys.prefix as well, which is the
    program/ directory holding soffice.exe and the wrapper itself.
    """
    dirs = []
    executable = sys.executable or ""
    if executable:
        try:
            if os.path.isfile(executable):
                dirs.append(os.path.dirname(os.path.abspath(executable)))
            elif os.path.isdir(executable):
                dirs.append(os.path.abspath(executable))
        except OSError:
            pass
    for root in (getattr(sys, "prefix", ""), getattr(sys, "base_prefix", "")):
        if not root:
            continue
        root = os.path.abspath(root)
        dirs.append(root)
        dirs.append(os.path.dirname(root))

    ordered = []
    for directory in dirs:
        if directory and directory not in ordered:
            ordered.append(directory)
    return ordered


def find_interpreter():
    """A Python that can actually be spawned as a subprocess.

    Used by the test suites, which start the server as a child process.
    sys.executable is not dependable under LibreOffice's Windows wrapper -- it
    can name something CreateProcess refuses with 'Access is denied' -- so
    prefer the program/python.exe wrapper, which also sets up the UNO
    environment that a bare python-core/bin/python.exe would not.
    """
    override = os.environ.get("LOCALC_MCP_PYTHON")
    if override and os.path.isfile(override):
        return override

    names = ("python.exe",) if os.name == "nt" else ("python3", "python")
    directories = interpreter_dirs()
    # Every directory is tried for a plain interpreter before any of them is
    # tried for one in bin/, so the program/ wrapper wins over the inner
    # python-core/bin/python.exe that sets up none of the UNO environment.
    for name in names:
        for directory in directories:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    for sub in ("bin", "Scripts"):
        for name in names:
            for directory in directories:
                candidate = os.path.join(directory, sub, name)
                if os.path.isfile(candidate):
                    return candidate

    if sys.executable and os.path.isfile(sys.executable):
        return sys.executable
    raise RuntimeError(
        "Could not find a Python to spawn (sys.executable=%r, sys.prefix=%r). "
        "Set LOCALC_MCP_PYTHON to the full path of LibreOffice's python.exe."
        % (sys.executable, getattr(sys, "prefix", ""))
    )


def _windows_registry_paths():
    """Ask Windows where LibreOffice is, rather than guessing at Program Files.

    Two registrations are worth consulting: the standard App Paths entry for
    soffice.exe, and the InstallPath the UNO SDK uses. Both are checked in the
    64- and 32-bit registry views, since a 32-bit LibreOffice on 64-bit Windows
    lands in the other one.
    """
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows only
        return []

    lookups = (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\LibreOffice\UNO\InstallPath"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\LibreOffice\UNO\InstallPath"),
    )
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)

    found = []
    for root, subkey in lookups:
        for view in views:
            try:
                with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | view) as key:
                    value = winreg.QueryValueEx(key, "")[0]
            except OSError:
                continue
            if not value:
                continue
            value = str(value).strip().strip('"')
            # App Paths names the executable; InstallPath names its folder.
            if value.lower().endswith(".exe"):
                found.append(value)
            else:
                found.append(os.path.join(value, "soffice.exe"))
    return found


def _soffice_candidates():
    """Every place worth looking for soffice, best guess first."""
    exe = "soffice.exe" if os.name == "nt" else "soffice"
    candidates = []

    explicit = os.environ.get("LOCALC_MCP_SOFFICE")
    if explicit:
        candidates.append(explicit)

    # We are most likely running under LibreOffice's bundled interpreter, so
    # soffice is sitting right next to it.
    for directory in interpreter_dirs():
        candidates.append(os.path.join(directory, exe))

    candidates.extend(_windows_registry_paths())

    # Environment variables rather than a hardcoded C:, which is wrong whenever
    # Windows or LibreOffice is installed somewhere else.
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(os.path.join(base, "LibreOffice", "program", exe))

    candidates.extend([
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
        "/opt/libreoffice/program/soffice",
        "/usr/lib/libreoffice/program/soffice",
    ])

    from shutil import which
    resolved = which(exe)
    if resolved:
        candidates.append(resolved)

    seen = set()
    ordered = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def _soffice_path():
    for candidate in _soffice_candidates():
        try:
            if os.path.exists(candidate):
                return candidate
        except OSError:
            continue
    return None


def _launch():
    path = _soffice_path()
    if not path:
        raise CalcError(
            "LibreOffice is not running with a UNO socket, and soffice could not be "
            "found. Looked in:\n  %s\n\nStart LibreOffice yourself with:\n"
            '  soffice --calc --accept="socket,host=%s,port=%d;urp;"\n'
            "or set LOCALC_MCP_SOFFICE to the full path of soffice."
            % ("\n  ".join(_soffice_candidates()), HOST, PORT)
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


# What LibreOffice going away actually looks like. It is not always a
# DisposedException: dying mid-call raises a plain RuntimeException reading
# "Binary URP bridge disposed during call", and matching only the class name
# meant the reconnect never fired for the commonest case of all.
_DISPOSED_MARKERS = (
    "disposedexception",
    "bridge disposed",
    "urp bridge",
    "connection has been closed",
    "connection closed",
)


def _is_disposed(exc):
    try:
        name = type(exc).__name__.lower()
    except Exception:
        name = ""
    try:
        message = str(exc).lower()
    except Exception:
        message = ""
    haystack = "%s %s" % (name, message)
    return any(marker in haystack for marker in _DISPOSED_MARKERS)


def _connection_alive(conn):
    """Is this connection still usable? Cheapest possible round trip."""
    try:
        conn.desktop.getComponents()
        return True
    except Exception:
        return False


def with_reconnect(fn):
    """Run fn(connection), reconnecting once if LibreOffice has gone away.

    LibreOffice dying mid-call surfaces as whatever UNO happened to be doing at
    the time: "Binary URP bridge disposed during call", "illegal object given!",
    "cannot get value URL" -- all different, all the same underlying event. So
    rather than recognising messages, ask the connection whether it still works.
    If it does, the error was real and belongs to the caller; if it does not,
    reconnect and run the operation again.
    """
    global _connection
    conn = connect()
    try:
        return fn(conn)
    except CalcError:
        raise
    except Exception as exc:
        if not (_is_disposed(exc) or not _connection_alive(conn)):
            raise
        log("LibreOffice is gone; reconnecting and retrying")
        _connection = None
        return fn(connect())


# --- documents ---------------------------------------------------------------

def uno_get(obj, name, default=None):
    """Read a UNO property, falling back rather than raising.

    getattr's default does not cover this: pyuno raises UnknownPropertyException
    when an object does not expose a property, and that is not AttributeError,
    so the default is never reached. A proxy for a document that is closing can
    also refuse a property it answered a moment earlier.
    """
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return default if value is None else value


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
    url = uno_get(doc, "URL", "")
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
        return doc.getTitle() or "Untitled"
    except Exception:
        return "Untitled"


def set_active_document(doc):
    global _active_doc_hint
    _active_doc_hint = uno_get(doc, "URL", "") or doc_label(doc)


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
            if (uno_get(d, "URL", "") or doc_label(d)) == _active_doc_hint:
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


def visible_rows(rng):
    """Absolute indices of the rows in `rng` that are not hidden by a filter.

    queryVisibleCells answers in one call, rather than asking each row whether
    it is visible.
    """
    try:
        found = rng.queryVisibleCells()
    except Exception:
        return None
    rows = set()
    for index in range(found.getCount()):
        addr = found.getByIndex(index).RangeAddress
        rows.update(range(addr.StartRow, addr.EndRow + 1))
    return rows


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
