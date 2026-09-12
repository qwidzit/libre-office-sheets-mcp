"""A direct UNO connection, for test assertions that must bypass the server."""

import threading

import uno


def _documents():
    """Every open Calc document, in the order LibreOffice enumerates them."""
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local)
    ctx = resolver.resolve(
        "uno:socket,host=127.0.0.1,port=2002;urp;StarOffice.ComponentContext")
    desktop = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", ctx)
    enum = desktop.getComponents().createEnumeration()
    docs = []
    while enum.hasMoreElements():
        component = enum.nextElement()
        try:
            if component.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                docs.append(component)
        except Exception:
            continue
    return docs


def _document():
    docs = _documents()
    if not docs:
        raise RuntimeError("no spreadsheet open")
    return docs[-1]


def _close_all():
    closed = 0
    for doc in _documents():
        try:
            doc.setModified(False)
            doc.close(False)
            closed += 1
        except Exception:
            pass
    return closed


def close_all(timeout=45):
    """Discard every open document, so a suite starts from a known state.

    Time-boxed on a daemon thread: a UNO call cannot be interrupted, and one
    that never returns would otherwise stall the whole run with no clue which
    step was responsible. If it overruns we say so and carry on -- the stuck
    thread dies with the process.
    """
    outcome = {}

    def work():
        try:
            outcome["closed"] = _close_all()
        except Exception as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        print("WARNING: closing open documents did not finish within %ds; "
              "continuing. A UNO call is blocked -- most likely a modal dialog "
              "in LibreOffice." % timeout, flush=True)
        return -1
    if "error" in outcome:
        print("WARNING: could not close open documents: %r" % outcome["error"],
              flush=True)
        return -1
    return outcome.get("closed", 0)


def undo_titles():
    """Newest first, as LibreOffice returns them."""
    return list(_document().getUndoManager().getAllUndoActionTitles())


def undo():
    _document().getUndoManager().undo()
