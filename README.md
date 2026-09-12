# LibreOffice Calc MCP server

[![tests](https://github.com/qwidzit/libre-office-sheets-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/qwidzit/libre-office-sheets-mcp/actions/workflows/tests.yml)

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

- Windows with LibreOffice installed. Every suite runs on each push against a
  real LibreOffice on both `windows-latest` (26.2) and Ubuntu (24.2), so the
  Windows paths are exercised rather than assumed. macOS should work too --
  only the paths differ -- but it is not covered by CI.
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
| `read_range` | Read cells as a tab-separated grid, optionally with formulas, optionally only the rows a filter leaves visible. |
| `write_range` | Write values and formulas. Sizes the block from the data. |
| `clear_range` | Clear contents, formatting, or both. |
| `recalculate` | Force formula recalculation. |
| `fill_cells` | Fill a formula or series down/across, adjusting relative references. |
| `copy_range` | Copy and paste: everything, values only, formats only, or transposed. |
| `clean_data` | Remove duplicate rows, or split one column into several. |
| `create_pivot_table` | Summarise a range by grouping and aggregating fields. |
| `conditional_format` | Colour cells by their value, by style name or by colour. |
| `data_validation` | Dropdown lists, number and date ranges, with input and error messages. |
| `page_setup` | Print area, orientation, fit-to-page, margins, headers, repeating rows. |
| `manage_names` | List, create and delete named ranges. |
| `manage_comments` | Add, read and delete cell comments. |
| `protect_sheet` | Lock and unlock cells, protect and unprotect the sheet. |
| `structure_edit` | Insert or delete rows and columns. |
| `manage_sheets` | Add, delete, rename, move, copy, activate sheets. |
| `sort_range` | Multi-key sort, by column letter or header name. |
| `find_cells` | Find matching cells, with regex support. |
| `find_replace` | Replace across a range, a sheet, or the document. |
| `filter_range` | Filter a table by criteria, clear a filter, or toggle AutoFilter dropdowns. |
| `format_range` | Named cell styles, font, colours, alignment, wrapping, number formats, borders, merging. |
| `size_cells` | Column widths, row heights, fit-to-contents, hide and show. |
| `freeze_panes` | Freeze header rows and columns. |
| `create_chart` | Column, bar, line, area, pie, donut, scatter and net charts, with axis titles, legend and data labels. |
| `run_uno_script` | Escape hatch for raw UNO. Disabled by default -- see below. |

Ranges accept `B2`, `A1:D20`, `Sheet2.A1:C9`, `A:C` for whole columns, `2:50` for
whole rows, and named ranges. Omit the range and most tools use the sheet's used
area.

## Things worth knowing

**Formulas work, including multi-argument ones.** Anything starting with `=`
is entered as a formula -- `IF`, `VLOOKUP`, `SUMIF`, `COUNTIF`, `CONCATENATE`,
`SUBTOTAL`, nested calls and so on.

**Formula argument separators are handled for you.** LibreOffice's API grammar
separates arguments with `;`, and a comma-separated call like
`=DATE(2026,3,15)` does not raise an error there -- it silently evaluates to
`#NAME?`. `write_range` rewrites commas to semicolons outside string literals,
so both styles work, and it tells you when it did. After writing formulas it
recalculates and reports any cells that ended up as `#REF!`, `#NAME?`,
`#DIV/0!` and so on, rather than leaving you to notice.

**Filling adjusts references, which is the point.** `fill_cells` is the fill
handle: write `=B2*C2` once in `D2`, fill through `D50`, and each row gets
`=B3*C3`, `=B4*C4` and so on -- relative and absolute (`$A$1`) references behave
exactly as Calc's own fill does. It also continues series: `1, 3, 5...` from a
step, or `Jan, Feb, Mar` from a single seed. `copy_range` covers paste special:
`all` adjusts references and brings formatting, `values` drops the formulas and
keeps the results, `formats` paints the styling across without touching content,
and `transpose` flips rows and columns.

**Protection is the usual worksheet pattern.** Cells are locked by default, so
`protect_sheet` with `unlock_cells` on the answer cells, then `protect`, gives a
sheet where only the intended cells can be typed into. Writes to locked cells
then fail with a clear error rather than silently doing nothing.

**Page setup also governs PDF export.** `save_document` to a `.pdf` uses whatever
the sheet's page style says, so set the print area, orientation and
fit-to-pages first if the output matters.

**Filtering hides rows, it does not delete them.** `filter_range` applies
criteria (`Qty > 5`, `Region equals North`, `Item begins_with B`, `top_values 3`,
`empty` ...), combines them with `match: "all"` or `"any"`, and reports how many
rows are left showing. `read_range` with `visible_only: true` then reads back
exactly what the user sees, keeping the sheet's real row numbers, so a filtered
table reads back as `2 4 5 6` rather than being silently renumbered. A plain
`read_range` still returns every row, and `calc_status` marks a filtered sheet so
neither of you is misled by the window showing fewer rows than the data holds.
`operation: "show_dropdowns"` turns on Calc's AutoFilter arrows so you can carry
on filtering by hand afterwards.

Formulas see filters the way Calc does: `SUM` covers every row, `SUBTOTAL(109,...)`
only the visible ones.

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
| `LOCALC_MCP_TIMEOUT` | `60` | Seconds to wait for a call before reporting LibreOffice as unresponsive. |
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

**"LibreOffice did not respond"** -- something modal is open in LibreOffice and
is blocking it. UNO calls are serviced on the main thread, so a dialog box, or
a cell left in edit mode, stops every one of them. Deal with it in the
LibreOffice window and try again. The server gives up after 60 seconds rather
than waiting forever; raise `LOCALC_MCP_TIMEOUT` if an operation is genuinely
that slow.

**Nothing happens / the server will not start** -- Claude Desktop keeps MCP
server logs under `%APPDATA%\Claude\logs\`. The server writes diagnostics to
stderr, which land there.

## Tests

Everything below runs in CI on Windows and Linux on every push; the badge at
the top reports the last run.

`scripts/smoke_protocol.py` checks the MCP wire protocol on its own -- no
LibreOffice needed:

```powershell
& "C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_protocol.py
```

Four further suites drive the server end to end against a live LibreOffice --
`smoke_calc.py` (reading, writing, formulas, formatting, sorting, charts,
saving), `smoke_extras.py` (dates, undo, file round trips), `smoke_filter.py`
(filtering and formula handling) and `smoke_course.py` (filling, paste special,
duplicates, text to columns, names, conditional formatting, validation, page
setup, comments, pivot tables, styles and protection). They need LibreOffice
listening on the UNO socket, and they create and close their own documents.

```powershell
& "C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_calc.py
& "C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_extras.py
& "C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_filter.py
& "C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_course.py
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
    data.py            fill, copy/paste special, clean, pivot tables
    document.py        conditional formatting, validation, page setup, names,
                       comments, protection
    edit.py            rows and columns, sheets, sort, filter, find, replace
    style.py           formatting, sizing, freeze, charts, raw UNO
scripts/               setup check, launcher, test suites
```
