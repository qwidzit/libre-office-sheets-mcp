"""Address parsing, value conversion and result formatting.

Nothing here touches UNO, so it is unit-testable under a plain interpreter.
"""

import datetime
import re

# --- column letters ----------------------------------------------------------

def col_to_index(letters):
    """'A' -> 0, 'AA' -> 26."""
    index = 0
    for ch in letters.upper():
        if not ("A" <= ch <= "Z"):
            raise ValueError("bad column reference: %r" % letters)
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def index_to_col(index):
    """0 -> 'A', 26 -> 'AA'."""
    if index < 0:
        raise ValueError("negative column index")
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def cell_name(col, row):
    return "%s%d" % (index_to_col(col), row + 1)


# --- range parsing -----------------------------------------------------------

_CELL = r"\$?[A-Za-z]{1,3}\$?[0-9]{1,7}"
_TAIL = re.compile(r"[.!](%s(?::%s)?|\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}|\$?[0-9]+:\$?[0-9]+)$" % (_CELL, _CELL))
_A1 = re.compile(r"^\$?([A-Za-z]{1,3})\$?([0-9]{1,7})$")
_COLS = re.compile(r"^\$?([A-Za-z]{1,3}):\$?([A-Za-z]{1,3})$")
_ROWS = re.compile(r"^\$?([0-9]{1,7}):\$?([0-9]{1,7})$")


def split_sheet(ref):
    """Split 'Sheet1.A1:C3' into ('Sheet1', 'A1:C3'). Returns (None, ref) if bare.

    Accepts both Calc's native '.' separator and Excel's '!', and strips the
    quoting Calc applies to sheet names containing spaces.
    """
    ref = ref.strip()
    match = _TAIL.search(ref)
    if not match:
        return None, ref
    sheet = ref[: match.start()].strip().lstrip("$")
    if len(sheet) >= 2 and sheet[0] == sheet[-1] == "'":
        sheet = sheet[1:-1].replace("''", "'")
    if not sheet:
        return None, ref
    return sheet, match.group(1)


class RangeSpec(object):
    """A rectangle of cells, resolved to 0-based inclusive coordinates."""

    __slots__ = ("start_col", "start_row", "end_col", "end_row")

    def __init__(self, start_col, start_row, end_col, end_row):
        self.start_col = start_col
        self.start_row = start_row
        self.end_col = end_col
        self.end_row = end_row

    @property
    def cols(self):
        return self.end_col - self.start_col + 1

    @property
    def rows(self):
        return self.end_row - self.start_row + 1

    @property
    def cells(self):
        return self.cols * self.rows

    def name(self):
        if self.start_col == self.end_col and self.start_row == self.end_row:
            return cell_name(self.start_col, self.start_row)
        return "%s:%s" % (
            cell_name(self.start_col, self.start_row),
            cell_name(self.end_col, self.end_row),
        )

    def __repr__(self):
        return "<RangeSpec %s>" % self.name()


def parse_range(ref, used=None):
    """Parse an A1 reference (already stripped of any sheet prefix).

    `used` is the sheet's used RangeSpec, needed to bound whole-column or
    whole-row references like 'A:C' or '2:100'.
    """
    ref = ref.strip().replace("$", "")
    if not ref:
        raise ValueError("empty range reference")

    if ":" in ref:
        left, right = ref.split(":", 1)
    else:
        left = right = ref

    cols = _COLS.match(ref)
    if cols:
        start_col = col_to_index(cols.group(1))
        end_col = col_to_index(cols.group(2))
        last_row = used.end_row if used is not None else 0
        return RangeSpec(min(start_col, end_col), 0, max(start_col, end_col), max(last_row, 0))

    rows = _ROWS.match(ref)
    if rows:
        start_row = int(rows.group(1)) - 1
        end_row = int(rows.group(2)) - 1
        last_col = used.end_col if used is not None else 0
        return RangeSpec(0, min(start_row, end_row), max(last_col, 0), max(start_row, end_row))

    first = _A1.match(left)
    second = _A1.match(right)
    if not first or not second:
        raise ValueError(
            "could not parse range %r -- expected A1 notation like 'B2', 'A1:D20' "
            "or 'Sheet2.A1:C9'" % ref
        )
    c1, r1 = col_to_index(first.group(1)), int(first.group(2)) - 1
    c2, r2 = col_to_index(second.group(1)), int(second.group(2)) - 1
    return RangeSpec(min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2))


# --- values ------------------------------------------------------------------

# LibreOffice error codes, from the ScErrorCodes list. Anything unmapped is
# reported by number rather than swallowed.
ERROR_NAMES = {
    501: "#NAME? (invalid character)",
    502: "#VALUE! (invalid argument)",
    503: "#VALUE! (invalid floating point operation)",
    504: "#VALUE! (parameter list error)",
    507: "#NAME? (pair missing)",
    508: "#NAME? (pair missing)",
    509: "#NAME? (missing operator)",
    510: "#NAME? (missing variable)",
    511: "#NAME? (missing variable)",
    512: "#NAME? (formula overflow)",
    513: "#NAME? (string overflow)",
    514: "#NAME? (internal overflow)",
    519: "#VALUE!",
    520: "#NAME? (internal syntax error)",
    521: "#NAME? (internal syntax error)",
    522: "#REF! (circular reference)",
    523: "#NUM! (calculation does not converge)",
    524: "#REF!",
    525: "#NAME?",
    526: "#NAME?",
    527: "#REF! (nesting too deep)",
    532: "#DIV/0!",
    533: "#DIV/0!",
}


def error_name(code):
    return ERROR_NAMES.get(code, "Err:%d" % code)


def serial_to_datetime(serial, null_date):
    """Convert a Calc date serial to a date/datetime using the doc's null date."""
    base = datetime.datetime(null_date[0], null_date[1], null_date[2])
    value = base + datetime.timedelta(days=float(serial))
    if value.hour or value.minute or value.second:
        return value
    return value.date()


def format_number(value):
    """Render a float the way a person would write it, not the way C does."""
    if value != value or value in (float("inf"), float("-inf")):
        return str(value)
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    text = repr(round(value, 10))
    if text.endswith(".0"):
        text = text[:-2]
    return text


def cell_text(value):
    """One cell -> one display string, safe to put in a tab-separated grid."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime.datetime) else value.isoformat()
    text = str(value)
    return text.replace("\t", "\\t").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def to_tsv(grid, spec, sheet_name):
    """Render a 2D grid as a tab-separated block with spreadsheet coordinates."""
    header = ["#"] + [index_to_col(spec.start_col + i) for i in range(spec.cols)]
    lines = ["\t".join(header)]
    for r, row in enumerate(grid):
        cells = [str(spec.start_row + r + 1)]
        cells.extend(cell_text(v) for v in row)
        lines.append("\t".join(cells))
    title = "%s.%s  (%d rows x %d cols)" % (sheet_name, spec.name(), spec.rows, spec.cols)
    return title + "\n" + "\n".join(lines)


def to_markdown(grid, spec, sheet_name):
    header = ["#"] + [index_to_col(spec.start_col + i) for i in range(spec.cols)]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for r, row in enumerate(grid):
        cells = [str(spec.start_row + r + 1)]
        cells.extend(cell_text(v).replace("|", "\\|") for v in row)
        lines.append("| " + " | ".join(cells) + " |")
    title = "%s.%s  (%d rows x %d cols)" % (sheet_name, spec.name(), spec.rows, spec.cols)
    return title + "\n" + "\n".join(lines)


def normalise_formula(text):
    """Translate Excel-style ',' argument separators to the ';' UNO expects.

    Calc's API formula grammar separates arguments with ';'. A comma-separated
    call like =DATE(2026,3,15) is not a syntax error there, it just silently
    evaluates to #NAME?, so the substitution has to happen before the write.
    Commas inside quoted strings and quoted sheet names are left alone, and the
    transform is a no-op on formulas that already use ';'.
    """
    if "," not in text:
        return text
    out = []
    in_double = in_single = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_double:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    out.append('""')
                    i += 2
                    continue
                in_double = False
            out.append(ch)
        elif in_single:
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    out.append("''")
                    i += 2
                    continue
                in_single = False
            out.append(ch)
        elif ch == '"':
            in_double = True
            out.append(ch)
        elif ch == "'":
            in_single = True
            out.append(ch)
        elif ch == ",":
            out.append(";")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def parse_color(value):
    """'#RRGGBB', 'RRGGBB', an int, or a handful of names -> a UNO color int."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    named = {
        "black": 0x000000, "white": 0xFFFFFF, "red": 0xFF0000, "green": 0x008000,
        "blue": 0x0000FF, "yellow": 0xFFFF00, "orange": 0xFFA500, "grey": 0x808080,
        "gray": 0x808080, "lightgrey": 0xD3D3D3, "lightgray": 0xD3D3D3,
        "purple": 0x800080, "cyan": 0x00FFFF, "magenta": 0xFF00FF, "none": -1,
        "transparent": -1,
    }
    if text in named:
        return named[text]
    text = text.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError("cannot parse colour %r -- use '#RRGGBB' or a name" % value)
    return int(text, 16)
