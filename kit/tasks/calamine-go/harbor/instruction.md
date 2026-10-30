# Port calamine's spreadsheet readers to Go

calamine is a Rust crate that reads Excel and OpenDocument spreadsheets: legacy `.xls` (BIFF2-BIFF8 inside a Compound File Binary container), `.xlsx`/`.xlsm` (SpreadsheetML in a zip), `.xlsb` (BIFF12 records in a zip) and `.ods` (OpenDocument). Your job is to port its readers to pure Go so that a Go command-line tool, `xlsdump`, prints exactly what calamine 0.37.0 reads from a workbook: the sheet list, every cell value with its type, the cell formulas, merged regions and defined names. The reference output on every graded workbook comes from the crate itself, so the Rust source is the specification, quirks included.

## Workspace

- `/app/calamine-go/`: the Go module you complete (`module calaminego`, Go 1.26.10 at `/usr/local/go`). It holds a stub `cmd/xlsdump/main.go` that only prints "not implemented", `internal/textdeps/` and `vendor/` with `golang.org/x/text` v0.42.0. That module is the only third-party code available; its `encoding/...` packages cover the code pages calamine decodes through `encoding_rs`. The directory is a git repository whose first commit is the starting point.
- `/app/reference/calamine-0.37.0/`: the crate's source at tag v0.37.0 (read-only): `src/cfb.rs`, `src/xls.rs`, `src/xlsx/`, `src/xlsb/`, `src/ods.rs`, `src/formats.rs`, `src/datatype.rs`, `src/utils.rs`, `src/attrs.rs`, `src/lib.rs`, `src/auto.rs`. There is no Rust toolchain in the image; read it, don't run it.
- `/app/samples/workbooks/`: 173 workbooks in all four formats: test files from the calamine repository and files produced by several writers. `/app/samples/expected/<file>.json` (`.json.gz` for large ones) is calamine's dump of each.
- `/app/tools/selfcheck.py`: builds `xlsdump` the way the grader does, runs the same gates and scores it on the samples. `/app/tools/units.py` is the comparison it uses.
- `/app/.timer/`: the time budget (see Time budget).

The dump covers the crate's reading API built with its `picture` feature: opening a workbook (including the pictures read at open time), sheet metadata, `worksheet_range`, `worksheet_formula`, `defined_names`, `vba_project`, `pictures_with_metadata`/`pictures`, `workbook_properties` for xlsx and xlsb, and for xlsx `merge_cells_by_sheet_name` (also xls), `hyperlinks_by_sheet_name`, the tables (`load_tables`, `table_names`, `table_by_name`) and the pivot tables (`pivot_tables`, `pivot_table_data`). Header-row options, chrono conversions and serde deserialization are out of scope.

## What to deliver

A Go program built from `/app/calamine-go` with

    cd /app/calamine-go && go build -o /tmp/xlsdump ./cmd/xlsdump

and run as `xlsdump <path-to-workbook>`. It prints one JSON document on stdout and exits 0. How you split the code into packages is up to you; a library package such as `calaminego/calamine` behind a thin `main` works well.

The reader is chosen by file extension, like calamine's `open_workbook_auto`: `.xls` and `.xla` use the xls reader; `.xlsx`, `.xlsm` and `.xlam` use the xlsx reader; `.xlsb` uses the xlsb reader; `.ods` uses the ods reader. Any other extension tries xls, xlsx, xlsb and ods in that order and takes the first that opens.

The program must be pure Go: no cgo, and no starting other processes. Graded runs have no network and no other spreadsheet software.

## Output format

    {
      "format": "xlsx",
      "sheets": [
        {"name": "Data", "type": "worksheet", "visible": "visible",
         "dims": [0, 0, 41, 3],
         "cells": [[0, 0, "s", "Region"], [1, 1, "f", 12.5], [1, 2, "d", 45123.25, "datetime", "2023-07-15T06:00:00.000"]],
         "formulas": [[41, 1, "SUM(B2:B41)"]],
         "merged": [[0, 0, 0, 3]],
         "hyperlinks": [[[2, 1, 2, 1], "https://example.com/", null, "link", null]]}
      ],
      "names": [["DataRange", "Data!$A$1:$D$42"]],
      "properties": {"creator": "Ann", "title": "Q3", "...": null},
      "vba": {"modules": [["Module1", "Attribute VB_Name = ..."]], "references": [["stdole", "OLE Automation", "C:\\..."]]},
      "pictures": [["Data", 4, 2, "png", "Picture 1", 2051, "9f86d0...sha256"]],
      "tables": [["Table1", "Data", ["Region", "Units"], [1, 0, 41, 1], [[1, 0, "s", "North"]]]],
      "pivots": [["Data", "PivotTable1", [[["s", "Region"], ["s", "Units"]], [["s", "North"], ["i", 12]]]]]
    }

- `format`: `xls`, `xlsx`, `xlsb` or `ods`, the reader that opened the file.
- `sheets`: one object per entry of calamine's `sheets_metadata()`, in that order. `type` is `worksheet`, `dialogsheet`, `macrosheet`, `chartsheet` or `vba` (`SheetType`); `visible` is `visible`, `hidden` or `veryhidden` (`SheetVisible`).
- `dims`: `[first_row, first_col, last_row, last_col]` of the `Range` that `worksheet_range(name)` returns, 0-based and absolute; `null` when the range is empty.
- `cells`: the cells of that range that are not `Data::Empty`, in row-major order (`Range::used_cells`), as `[row, col, tag, ...]` with absolute positions:
  - `Data::Int(n)` is `["i", n]` and `Data::Float(x)` is `["f", x]`;
  - `Data::String(s)` is `["s", s]` (an empty string is a value too) and `Data::Bool(b)` is `["b", b]`;
  - `Data::DateTime(dt)` is `["d", serial, kind, text]`: the raw serial number, `"datetime"` or `"timedelta"`, and `ExcelDateTime::to_ymd_hms_milli()` written as `YYYY-MM-DDTHH:MM:SS.mmm` with zero padding (this is where the 1904 date system shows);
  - `Data::DateTimeIso(s)` is `["di", s]` and `Data::DurationIso(s)` is `["du", s]`;
  - `Data::Error(e)` is `["e", text]`, with the text of `CellErrorType`'s `Display` (`#DIV/0!`, `#N/A`, `#NAME?`, `#NULL!`, `#NUM!`, `#REF!`, `#VALUE!`, `#DATA!`).
  - A float that is NaN or infinite is written as the string `"NaN"`, `"inf"` or `"-inf"`.
- `formulas`: the non-empty strings of `worksheet_formula(name)` as `[row, col, text]`, row-major, absolute positions.
- `merged`: for xlsx and xls, `merge_cells_by_sheet_name(name)` as `[first_row, first_col, last_row, last_col]` lists in calamine's order; `null` for xlsb and ods.
- `names`: `defined_names()` as `[name, formula]` pairs, in order.
- `hyperlinks` (per sheet): for xlsx, `hyperlinks_by_sheet_name(name)` as `[[first_row, first_col, last_row, last_col], target, location, displayed_text, tooltip]`, with `null` for absent fields; `null` for the other formats.
- `properties`: for xlsx and xlsb, `workbook_properties()` as an object with the 17 keys `creator`, `last_modified_by`, `created`, `modified`, `title`, `subject`, `description`, `keywords`, `category`, `content_status`, `revision`, `version`, `application`, `app_version`, `company`, `template`, `manager` (`null` when unset); `null` for xls and ods.
- `vba`: `null` when `vba_project()` returns `None`; otherwise `{"modules": [[name, source], ...], "references": [[name, description, path], ...]}` with the modules in `get_module_names()` order, each source from `get_module`, and `get_references()` in order (the path as text).
- `pictures`: one `[sheet_name, row, col, extension, name, byte_length, sha256_hex_of_data]` per picture, in any order. For xlsx these come from `pictures_with_metadata()`; for the other formats from `pictures()`, with sheet `""`, row and col `0` and name `""`; an empty list when there are none.
- `tables`: for xlsx, `load_tables()` then one `[name, sheet_name, columns, dims, cells]` per entry of `table_names()`, where the last three come from `table_by_name(name)` (its data range, written like a sheet's `dims` and `cells`); `null` for the other formats.
- `pivots`: for xlsx, one `[sheet_name, pivot_name, rows]` per entry of `pivot_tables()`'s `get_pivot_tables_by_name_and_sheet()`, where `rows` lists every item of `pivot_table_data(...)` and each value is a tagged value as in `cells` without the position (`["i", 5]`, `["s", "x"]`, ...) or `null` for `Data::Empty`; `null` for the other formats.
- When calamine returns an `Err` for one of these parts (a sheet's range, formulas, merged regions or hyperlinks, the properties, the VBA project, the tables, or one table or pivot table's data), put the string `"error"` in its place (and `null` for `dims`). When the workbook does not open, print `{"error": "open", "detail": "..."}`. Neither case is scored, and neither are calamine's own `Unrecognised formula ...` placeholder strings.

Numbers may use any valid JSON spelling (`44197`, `44197.0` and `4.4197e4` are equal) and are compared as floating-point values with a relative tolerance of 1e-12, except the value of an `"i"` cell, which must be a JSON integer. Strings, tags, positions and list lengths must match exactly. Key order and whitespace don't matter.

## Building and checking your work

    cd /app/calamine-go && go build ./...      # the environment already sets GOFLAGS=-mod=vendor, CGO_ENABLED=0
    python3 /app/tools/selfcheck.py            # gates, build, every sample, per-format scores
    python3 /app/tools/selfcheck.py --only .ods --show 20
    python3 /app/tools/selfcheck.py --no-build --bin /tmp/xlsdump

`selfcheck.py` prints a score per format, the mean of the four (the same formula as the grade, on the samples) and the first difference for each failing unit. The expected files are plain calamine dumps, so `python3 -m json.tool` and `diff` work on them too. When a sample disagrees, read the matching Rust function before guessing: the answer is almost always one specific branch in `xls.rs`, `cfb.rs`, `xlsx/cells_reader.rs`, `xlsb/mod.rs` or `ods.rs`.

## Scoring

The grader copies `/app/calamine-go` (symbolic links are not copied), restores `go.mod`, `go.sum` and `vendor/` to the shipped versions, and builds `./cmd/xlsdump` with Go 1.26.10, `-mod=vendor` and `CGO_ENABLED=0`, as an unprivileged user with no network. These are hard gates; failing any of them scores exactly 0:

1. The build succeeds.
2. Your packages (everything outside `vendor/`) import none of `C`, `os/exec`, `syscall`, `plugin`, `runtime/cgo`, and contain no `go:linkname`, `StartProcess`, `ForkExec` or cgo directives, and no `.s`, `.c`, `.cc`, `.cpp`, `.h` or `.syso` files.
3. The Go toolchain under `/usr/local/go` is unmodified.

`selfcheck.py` runs gates 1 and 2 the same way.

It then runs `xlsdump` once on each workbook of a fixed hidden set: about 820 workbooks. They are the calamine test files that are not among the samples, plus workbooks generated for this task by XlsxWriter, openpyxl, xlwt, LibreOffice (recalculated on load) and hand-written BIFF5, BIFF8, BIFF12, SpreadsheetML and OpenDocument writers. They exercise the same features as the samples, with different content. Each run gets 20 seconds of wall time, 40 seconds of CPU time and 4 GB of address space. A timeout, a crash, a non-zero exit or output that isn't JSON fails every unit of that workbook.

A workbook is split into units, and each unit is all-or-nothing:

- the sheet list (`name`, `type`, `visible` of every sheet, in order);
- `names`, when calamine reports any;
- for each sheet: `dims` together with `cells`, when the sheet has cells; `formulas`, when it has formulas; `merged`, when it has merged regions; `hyperlinks`, when it has hyperlinks;
- `properties`, when any property is set;
- each VBA module (matched by name) and the VBA reference list, when non-empty;
- each picture (as a multiset: a picture that occurs twice needs two copies);
- each table and each pivot table, by position.

Empty lists and `"error"` entries in the reference are not units, so printing empty output earns nothing.

Units fall into seven buckets: the sheet list, names, cells, formulas and merged regions count towards the workbook's format (`xls`, `xlsx`, `xlsb` or `ods`); VBA modules and references towards `vba`; pictures towards `pictures`; properties, hyperlinks, tables and pivot tables towards `objects`.

    file score in a bucket = units of the bucket reproduced / units of the bucket in the file
    bucket score           = mean file score over the hidden workbooks that have units in the bucket
    reward                 = mean of the seven bucket scores

The denominator is fixed: every hidden workbook counts in each bucket where it has units, whether or not your program handles it. The untouched stub scores 0. A complete, faithful port scores 1.0, which is what the reference port reaches.

## Time budget

You have 8 hours. The real remaining budget is in `/app/.timer/remaining_secs` (`elapsed_secs` and `budget_secs` sit beside it); `alert_30min`, `alert_10min` and `alert_5min` appear there as the end nears. The container clock says nothing about your budget, so `cat /app/.timer/remaining_secs` before starting a long piece of work.

## Constraints

- Reproduce calamine 0.37.0, including behaviour that looks like a bug: the hidden expectations come from the crate, not from the file-format specifications. Examples are how `parse_formula` in `xls.rs` decodes `PtgRef3d` columns, how `read_styles` in `xlsb/mod.rs` skips records it does not match, which numbers count as dates in `formats.rs`, and the row arithmetic of `get_range` in `ods.rs`. Rust release builds wrap on integer overflow and saturate float-to-integer casts; mirror that where it changes output. Where the crate would panic, any non-zero exit or `"error"` is fine, because those cases are not scored.
- Text decoding follows `encoding_rs` through the `codepage` crate's table (in `cfb.rs` via `XlsEncoding`); the vendored `golang.org/x/text` encodings implement the same WHATWG tables. Note that `Encoding::decode` honours a byte-order mark.
- No new third-party modules (the grader restores `go.mod` and `vendor/`), no cgo, no external processes, and no changes to `/usr/local/go`.
- Outputs for the samples are visible, so code that recognises sample files earns nothing on the hidden set.

## Operating rules

Nobody will answer questions during the run, so make the calls yourself and keep moving. Get valid JSON out for all four formats early, then deepen one bucket at a time; each bucket is a seventh of the reward, and a reader that opens files and gets most sheets right already scores. Keep `go build ./...` green: a tree that does not compile scores 0 however much of it is right. After each change run `selfcheck.py`, keep what raises the score and back out what doesn't. The hidden set is about five times the size of the samples and uses different files, so port the logic from the Rust source instead of tuning to what you can see. Check `/app/.timer/remaining_secs` before long efforts, commit working states to the local git repository as you go, and keep the last 20 minutes for a final build and self-check.
