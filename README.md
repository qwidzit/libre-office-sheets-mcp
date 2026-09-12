# LibreOffice Calc MCP server

An MCP server that lets Claude read and edit a **live** LibreOffice Calc
spreadsheet. You keep the document open on screen and watch the cells change as
Claude works.

Built for personal use: no dependencies, no build step, no package manager.

```
Claude Desktop / Claude Code
        |  MCP over stdio
        v
   server.py            <- run by LibreOffice's own python.exe
        |  UNO / URP socket on 127.0.0.1:2002
        v
   soffice.exe --calc   <- your open spreadsheet
```

## Why there is nothing to install

The server talks MCP directly over stdio (newline-delimited JSON-RPC) using only
the Python standard library, and LibreOffice already ships a Python that has the
`uno` bindings built in. So you point Claude at LibreOffice's interpreter and the
server file, and that is the whole install. No `pip`, no virtualenv, no admin
rights.

## Requirements

- Windows with LibreOffice installed (tested against 24.2; earlier 7.x should be
  fine). macOS and Linux work too -- only the paths differ.
- LibreOffice's bundled Python, normally at
  `C:\Program Files\LibreOffice\program\python.exe`.

Check it:

```powershell
& "C:\Program Files\LibreOffice\program\python.exe" -c "import uno; print('ok')"
```

If that prints `ok`, you are ready.

## Setup

**1. Get the code**

```powershell
git clone <this repo> C:\Users\YOU\libre-office-sheets-mcp
```

**2. Verify the setup**

```powershell
& "C:\Program Files\LibreOffice\program\python.exe" `
  C:\Users\YOU\libre-office-sheets-mcp\scripts\check-setup.py
```

This reports the interpreter, whether `uno` imports, where `soffice.exe` is, and
whether it can reach a running LibreOffice.

**3. Register the server**

*Claude Desktop* -- edit `%APPDATA%\Claude\claude_desktop_config.json` (see
`claude_desktop_config.example.json`):

```json
{
  "mcpServers": {
    "libreoffice-calc": {
      "command": "C:\\Program Files\\LibreOffice\\program\\python.exe",
      "args": ["C:\\Users\\YOU\\libre-office-sheets-mcp\\server.py"]
    }
  }
}
```

Restart Claude Desktop.

*Claude Code*:

```powershell
claude mcp add libreoffice-calc -- `
  "C:\Program Files\LibreOffice\program\python.exe" `
  "C:\Users\YOU\libre-office-sheets-mcp\server.py"
```

**4. Use it**

Ask Claude something like *"what's in my open spreadsheet?"*. The server connects
to LibreOffice, starting it if it is not already running. To start it yourself
first:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-libreoffice.ps1
```

Already have a spreadsheet open? Run that script anyway -- LibreOffice hands the
`--accept` flag to the running instance and opens the socket on it, so your
document stays exactly where it is.

## Tools

| Tool | What it does |
| --- | --- |
| `calc_status` | Connection, open documents, sheets and their used ranges. Start here. |
| `open_document` | Open a file, or create a new empty spreadsheet. |
| `save_document` | Save in place, or save a copy as ods / xlsx / xls / csv / pdf / html. |
| `read_range` | Read cells as a tab-separated grid, optionally with formulas. |
| `write_range` | Write values and formulas. Sizes the block from the data. |
| `clear_range` | Clear contents, formatting, or both. |
| `recalculate` | Force formula recalculation. |
| `structure_edit` | Insert or delete rows and columns. |
| `manage_sheets` | Add, delete, rename, move, copy, activate sheets. |
| `sort_range` | Multi-key sort, by column letter or header name. |
| `find_cells` | Find matching cells, with regex support. |
| `find_replace` | Replace across a range, a sheet, or the document. |
| `format_range` | Font, colours, alignment, wrapping, number formats, borders, merging. |
| `size_cells` | Column widths, row heights, fit-to-contents, hide and show. |
| `freeze_panes` | Freeze header rows and columns. |
| `create_chart` | Column, bar, line, area, pie, donut, scatter and net charts. |
| `run_uno_script` | Escape hatch for raw UNO. Disabled by default -- see below. |

Ranges accept `B2`, `A1:D20`, `Sheet2.A1:C9`, `A:C` for whole columns, `2:50` for
whole rows, and named ranges. Omit the range and most tools use the sheet's used
area.

## Things worth knowing

**Formula argument separators are handled for you.** LibreOffice's API grammar
separates arguments with `;`, and a comma-separated call like
`=DATE(2026,3,15)` does not raise an error there -- it silently evaluates to
`#NAME?`. `write_range` rewrites commas to semicolons outside string literals,
so both styles work, and it tells you when it did. After writing formulas it
recalculates and reports any cells that ended up as `#REF!`, `#NAME?`,
`#DIV/0!` and so on, rather than leaving you to notice.

**Undo mostly works, with one documented gap.** Every change goes onto
LibreOffice's own undo stack and a whole written block is a single Ctrl+Z. The
exception, measured on LibreOffice 24.2: a bulk write into cells that were
*empty* beforehand cannot be undone -- the undo entry is consumed but the
content stays. Overwriting cells that already held data undoes correctly, as do
clears, formatting, row and column edits, sorting, replace and every sheet
operation. So the case that will not undo is also the case where nothing was
lost. Even so, `save_document` to a copy before anything sweeping.

The server deliberately does **not** wrap operations in UNO undo contexts:
grouping them looks tidier in the undo list but breaks undo altogether, because
`undo()` pops the composite entry without reverting what is inside it.

**Nothing is written to disk until you save.** Edits are live in the open
window but the file on disk is untouched until `save_document`.

**Dates come back as dates.** Calc stores dates as serial numbers. `read_range`
checks each column's number format and converts date-formatted columns using the
document's null date, including dates produced by formulas.

## Configuration

All optional, set in the `env` block of the MCP config:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LOCALC_MCP_PORT` | `2002` | UNO socket port. |
| `LOCALC_MCP_HOST` | `127.0.0.1` | UNO socket host. |
| `LOCALC_MCP_AUTOLAUNCH` | `1` | Start LibreOffice if it is not reachable. |
| `LOCALC_MCP_LAUNCH_TIMEOUT` | `45` | Seconds to wait for a launched instance. |
| `LOCALC_MCP_SOFFICE` | auto | Full path to `soffice.exe`. |
| `LOCALC_MCP_ENABLE_EXEC` | `0` | Set to `1` to enable `run_uno_script`. |

`run_uno_script` executes arbitrary Python against your open documents. It is
off by default and only worth enabling when you want Claude to reach a corner of
the UNO API the other tools do not cover.

## Troubleshooting

**"Could not import the 'uno' module"** -- the server is being run by the wrong
Python. The `command` must be LibreOffice's own `python.exe`.

**"Could not reach LibreOffice"** -- LibreOffice is running without a UNO
socket. Run `scripts\start-libreoffice.ps1`, or set `LOCALC_MCP_AUTOLAUNCH=1`.

**Saving fails with an IO error** -- the target file is usually already open in
another window, or a `.~lock.<name>#` file is stranded next to it.

**Nothing happens / the server will not start** -- Claude Desktop keeps MCP
server logs under `%APPDATA%\Claude\logs\`. The server writes diagnostics to
stderr, which land there.

## Tests

`scripts/smoke_protocol.py` checks the MCP wire protocol on its own -- no
LibreOffice needed:

```powershell
& "C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_protocol.py
```

`scripts/smoke_calc.py` and `scripts/smoke_extras.py` drive the server end to end
against a live LibreOffice: reading, writing, formulas, formatting, sorting,
charts, saving, reopening, date conversion and undo. They need LibreOffice
listening on the UNO socket, and they create and close their own documents.

```powershell
& "C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_calc.py
& "C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_extras.py
```

## Layout

```
server.py              entry point
locmcp/
  jsonrpc.py           newline-delimited JSON-RPC over stdio
  protocol.py          MCP initialize / tools/list / tools/call
  registry.py          tool registration and schema helpers
  bridge.py            UNO connection, document/sheet/range resolution
  convert.py           A1 parsing, value conversion, output formatting
  tools/
    core.py            status, open/save, read/write/clear, recalculate
    edit.py            rows and columns, sheets, sort, find, replace
    style.py           formatting, sizing, freeze, charts, raw UNO
scripts/               setup check, launcher, test suites
```
