# LibreOffice Calc for Claude

[![tests](https://github.com/qwidzit/libre-office-sheets-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/qwidzit/libre-office-sheets-mcp/actions/workflows/tests.yml)

This lets Claude work directly in your LibreOffice Calc spreadsheets. You keep
the spreadsheet open on screen, ask Claude for something in plain English, and
watch the cells change as it works.

You can ask for things like:

> *Add a Total column that multiplies Quantity by Price, then make the header
> row bold and fit the columns to their contents.*

> *Sort this by revenue, highest first, keeping the header row where it is.*

> *Highlight anything over budget in red.*

> *Make a chart of sales by region and put it to the right of the table.*

> *Turn column A into a dropdown that only accepts Yes or No.*

> *Show me only the rows for the North region.*

Nothing is sent anywhere unusual: Claude talks to the copy of LibreOffice
already running on your computer.

---

# Setting it up

**This takes about five minutes and needs no technical knowledge.** There is no
command line to learn, nothing to compile, and nothing to install beyond
LibreOffice itself. Every step below is clicking, copying and pasting.

## Before you start

You need two free programs:

- **LibreOffice** — if you don't have it, download it from
  [libreoffice.org/download](https://www.libreoffice.org/download) and install
  it with all the default options.
- **Claude Desktop** — from [claude.ai/download](https://claude.ai/download).

## Step 1 — Download these files

1. Go to the [project page on GitHub](https://github.com/qwidzit/libre-office-sheets-mcp).
2. Click the green **Code** button, then **Download ZIP**.
3. Find the downloaded ZIP file (usually in your **Downloads** folder), right-click
   it, and choose **Extract All…**
4. When it asks where to put the files, type this exactly:

   ```
   C:\libreoffice-mcp
   ```

   and click **Extract**.

> **Check it worked:** open `C:\libreoffice-mcp` and you should see a file called
> **server.py** and one called **Check setup.bat**. If instead you see a single
> folder with a long name, open it, select everything inside, and move it up into
> `C:\libreoffice-mcp` so that `server.py` sits directly in that folder.

## Step 2 — Run the setup check

In `C:\libreoffice-mcp`, **double-click the file called `Check setup.bat`**.

A black window will open and check that everything is in place. You should see
something ending like this:

```
Everything works. Copy the block below into Claude Desktop's config file
(Settings > Developer > Edit Config), then restart Claude Desktop.

{
  "mcpServers": {
    "libreoffice-calc": {
      "command": "C:\\Program Files\\LibreOffice\\program\\python.exe",
      "args": [
        "C:\\libreoffice-mcp\\server.py"
      ]
    }
  }
}
```

**Leave this window open** — you need to copy that block in the next step. To
copy from a black window: click and drag across the text to select it, then
press **Ctrl+C**.

If you get an error instead, skip to [If something goes
wrong](#if-something-goes-wrong) below.

## Step 3 — Tell Claude about it

1. Open **Claude Desktop**.
2. Open its settings:
   - **Windows:** click the menu in the top-left, then **File ▸ Settings**
   - **Mac:** **Claude ▸ Settings** in the menu bar
3. Go to the **Developer** section and click **Edit Config**.
4. A folder opens with a file called **claude_desktop_config.json**. Right-click
   that file and choose **Open with ▸ Notepad**.

Now, what you do depends on what's already in the file:

**If the file is empty, or contains only `{}`** — delete whatever is there and
paste in the whole block you copied in Step 2.

**If the file already has other things in it**, it will look something like this:

```json
{
  "mcpServers": {
    "something-else": {
      "command": "..."
    }
  }
}
```

In that case, paste only the `"libreoffice-calc": { ... }` part inside the
existing `mcpServers` section, and put a comma after the entry before it:

```json
{
  "mcpServers": {
    "something-else": {
      "command": "..."
    },
    "libreoffice-calc": {
      "command": "C:\\Program Files\\LibreOffice\\program\\python.exe",
      "args": ["C:\\libreoffice-mcp\\server.py"]
    }
  }
}
```

Save the file (**Ctrl+S**) and close Notepad.

> **The double backslashes are not a mistake.** `C:\\libreoffice-mcp\\server.py`
> is correct in this file. Single backslashes will stop it working.

## Step 4 — Restart Claude Desktop

Close Claude Desktop completely and open it again. Closing it to the system tray
is not enough — right-click its icon near the clock and choose **Quit** if it's
hiding there.

## Step 5 — Try it

Open Claude Desktop and type:

> *What's in my open spreadsheet?*

Claude will start LibreOffice if it isn't already running, and tell you what it
found. That's it — you're set up.

---

# Using it day to day

**Just describe what you want.** You don't need to know the names of anything in
this project. "Sort by date", "add up column D", "make the totals bold" all work.

**Your spreadsheet stays open in front of you.** Changes appear live, so you can
watch and stop Claude if it heads somewhere you didn't intend.

**Nothing is saved until you say so.** Claude's changes are in the open window
only. Ask it to save, or press **Ctrl+S** yourself. If you close without saving,
the changes are gone — which is also a handy escape hatch.

**Ctrl+Z works** for undoing what Claude did, with one exception noted below.

**Before anything drastic**, ask Claude to save a copy first — *"save a copy as
budget-backup.ods before you start"*. Good advice with any tool, not just this one.

## Things worth knowing

**Undo has one gap.** Everything Claude does goes onto LibreOffice's normal undo
stack, and a whole block of changes undoes in one press of Ctrl+Z. The exception:
when Claude fills in cells that were *completely empty* beforehand, LibreOffice
cannot undo that. Note that this is also the case where nothing was lost — the
cells were empty. Changes that overwrite existing data undo correctly.

**If Claude seems stuck**, look at the LibreOffice window. A dialog box waiting
for an answer, or a cell still in edit mode with the cursor blinking in it, stops
LibreOffice responding to anything. Deal with it and ask Claude to try again.
After a minute Claude will tell you this itself rather than waiting forever.

**Filtering hides rows, it doesn't delete them.** If a table suddenly looks
short, it may be filtered. Ask Claude to clear the filter.

**Printing and PDFs** use the page setup. If you want a PDF to look right, ask
for the page setup first — *"set it to landscape, fit to one page wide, and
repeat the header row"* — and then ask for the PDF.

---

# If something goes wrong

### "Could not find LibreOffice on this computer"

LibreOffice isn't installed, or it's somewhere unusual. Install it from
[libreoffice.org/download](https://www.libreoffice.org/download) using the
default options, then run `Check setup.bat` again.

### The black window flashes up and disappears

It's finishing too fast to read. Instead of double-clicking, open the
`C:\libreoffice-mcp` folder, hold **Shift**, right-click an empty part of the
folder, choose **Open PowerShell window here** or **Open in Terminal**, and then
type `.\"Check setup.bat"` and press Enter. The window will stay open.

### Claude says it can't find the spreadsheet tools

Three things to check, in order:

1. Did you fully quit and reopen Claude Desktop after editing the config?
2. Open `claude_desktop_config.json` again and check the backslashes are doubled
   (`C:\\libreoffice-mcp\\server.py`, not `C:\libreoffice-mcp\server.py`).
3. Check that the file `C:\libreoffice-mcp\server.py` really exists at exactly
   that path.

### "LibreOffice did not respond"

Something in LibreOffice is waiting for you. Switch to the LibreOffice window,
close any dialog box that's open, press **Escape** to leave any cell you were
editing, and ask Claude to try again.

### Saving fails

The file is probably already open in another window. Close it and try again. If
that isn't it, look in the same folder for a hidden file whose name starts with
`.~lock` and delete it.

### Nothing above helped

Run `Check setup.bat` again and read the whole output — it lists every place it
looked for LibreOffice, and marks the ones it found with an `[x]`. Claude Desktop
also keeps logs: press **Windows key + R**, type `%APPDATA%\Claude\logs`, and
press Enter.

---

# Reference

Everything from here down is detail you don't need for everyday use.

## What Claude can do

| Tool | What it does |
| --- | --- |
| `calc_status` | Connection, open documents, sheets and their used ranges. |
| `open_document` | Open a file, or create a new empty spreadsheet. |
| `save_document` | Save in place, or save a copy as ods / xlsx / xls / csv / pdf / html. |
| `read_range` | Read cells as a grid, optionally with formulas, optionally only visible rows. |
| `write_range` | Write values and formulas. |
| `clear_range` | Clear contents, formatting, or both. |
| `recalculate` | Force formula recalculation. |
| `fill_cells` | Fill a formula or series down or across, adjusting references. |
| `copy_range` | Copy and paste: everything, values only, formats only, or transposed. |
| `clean_data` | Remove duplicate rows, or split one column into several. |
| `create_pivot_table` | Summarise a range by grouping and aggregating fields. |
| `conditional_format` | Colour cells automatically by their value. |
| `data_validation` | Dropdown lists, number and date limits, input and error messages. |
| `page_setup` | Print area, orientation, fit-to-page, margins, headers, repeating rows. |
| `manage_names` | List, create and delete named ranges. |
| `manage_comments` | Add, read and delete cell comments. |
| `protect_sheet` | Lock and unlock cells, protect and unprotect the sheet. |
| `structure_edit` | Insert or delete rows and columns. |
| `manage_sheets` | Add, delete, rename, move, copy, activate sheets. |
| `sort_range` | Multi-key sort, by column letter or header name. |
| `find_cells` | Find matching cells, with regular expressions. |
| `find_replace` | Replace across a range, a sheet, or the document. |
| `filter_range` | Filter by criteria, clear a filter, AutoFilter dropdowns, advanced filters. |
| `outline` | Group rows or columns so they collapse and expand. |
| `format_range` | Cell styles, font, colours, alignment, number formats, borders, merging. |
| `size_cells` | Column widths, row heights, fit-to-contents, hide and show. |
| `freeze_panes` | Freeze header rows and columns. |
| `create_chart` | Charts, with titles, axis labels, legend and data labels. |
| `run_uno_script` | Escape hatch for raw UNO. Disabled unless switched on. |

Ranges accept `B2`, `A1:D20`, `Sheet2.A1:C9`, `A:C` for whole columns, `2:50`
for whole rows, and named ranges.

## How it works

```
Claude Desktop
        |  MCP over stdio
        v
   server.py            <- run by LibreOffice's own python.exe
        |  UNO socket on 127.0.0.1:2002
        v
   soffice.exe --calc   <- your open spreadsheet
```

There is nothing to install because the server speaks MCP directly using only
Python's standard library, and LibreOffice already ships a Python with the UNO
bindings built in. So Claude runs LibreOffice's own interpreter against
`server.py`, and that is the entire installation.

## Notes for the curious

**Formula separators are handled for you.** LibreOffice's programming interface
separates arguments with `;`, and a comma-separated call like `=DATE(2026,3,15)`
doesn't fail there — it silently evaluates to `#NAME?`. Commas outside quoted
text are rewritten before writing, and any cell that ends up as an error is
reported back rather than left to be discovered later.

**Advanced filters** work two ways: a list of conditions, or a criteria block
laid out the way Calc's own Advanced Filter dialog expects (a header row, then
one row per set of conditions, ANDed across a row and ORed between rows). Either
can copy the matching rows somewhere else instead of hiding the rest, and can
drop duplicates. The criteria block is parsed by this project, because
LibreOffice does not expose that part through its API.

**Outline levels** only do something where groups are nested inside one another.
For a single level of grouping, collapse and expand are what you want.

**Not covered:** images and shapes, macros, hyperlinks, Goal Seek. Sparklines
are impossible rather than merely absent — LibreOffice does not expose them
through its API at all.

## Settings

All optional, in the `env` section of the Claude Desktop config entry:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LOCALC_MCP_PORT` | `2002` | Port LibreOffice listens on. |
| `LOCALC_MCP_HOST` | `127.0.0.1` | Host LibreOffice listens on. |
| `LOCALC_MCP_AUTOLAUNCH` | `1` | Start LibreOffice if it isn't running. |
| `LOCALC_MCP_LAUNCH_TIMEOUT` | `45` | Seconds to wait for it to start. |
| `LOCALC_MCP_TIMEOUT` | `60` | Seconds before reporting LibreOffice as unresponsive. |
| `LOCALC_MCP_SOFFICE` | auto | Full path to `soffice.exe`. |
| `LOCALC_MCP_PYTHON` | auto | Full path to the Python used to start the server. |
| `LOCALC_MCP_ENABLE_EXEC` | `0` | Set to `1` to enable `run_uno_script`. |

`run_uno_script` runs arbitrary Python against your open documents. It is off by
default and only worth switching on if you want Claude to reach a corner of
LibreOffice the other tools don't cover.

## Other platforms

macOS and Linux work the same way; only the paths differ. Point the config at
LibreOffice's Python — `/Applications/LibreOffice.app/Contents/Resources/python`
on macOS, or a system `python3` with `python3-uno` installed on Linux — and at
`server.py`. Run `scripts/check-setup.py` with that interpreter to confirm, and
it will print the config to use. The `.bat` files are Windows-only; on other
systems run the scripts directly.

## Running the tests

Every suite runs in CI on each push, against a real LibreOffice on both Windows
and Linux. To run them yourself, use LibreOffice's Python:

```
"C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_protocol.py
"C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_calc.py
"C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_extras.py
"C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_filter.py
"C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_course.py
"C:\Program Files\LibreOffice\program\python.exe" scripts\smoke_advanced.py
```

`smoke_protocol.py` checks the MCP wire protocol on its own and needs no
LibreOffice. The rest drive the server against a running LibreOffice and create
their own documents.

## Layout

```
server.py              entry point
Check setup.bat        double-click to verify the setup
Start LibreOffice.bat  double-click to open Calc with the connection enabled
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
    edit.py            rows and columns, sheets, sort, filter, outline, search
    style.py           formatting, sizing, freeze, charts, raw UNO
scripts/               setup check, launcher, test suites
```
