"""A direct UNO connection, for test assertions that must bypass the server."""

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


def close_all():
    """Discard every open document, so a suite starts from a known state."""
    closed = 0
    for doc in _documents():
        try:
            doc.setModified(False)
            doc.close(False)
            closed += 1
        except Exception:
            pass
    return closed


def undo_titles():
    """Newest first, as LibreOffice returns them."""
    return list(_document().getUndoManager().getAllUndoActionTitles())


def undo():
    _document().getUndoManager().undo()
