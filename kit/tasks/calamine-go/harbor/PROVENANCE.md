# Provenance

## Source

calamine, the pure-Rust reader for Excel and OpenDocument spreadsheets: https://github.com/tafia/calamine, release v0.37.0 (tag commit f2c5948242fdfe390e292313a1f87f9db19b9633, released 2026-10-18, MIT licence). The image unpacks the crate as published on crates.io, `calamine-0.37.0.crate` (sha256 c9ca341b94bc4b29e08970b1a03914fad2dfe177e2ecb67fcd6de9046004aafb, the checksum in the crates.io index; its `.cargo_vcs_info.json` names the same commit). Its `src/` is byte-identical to the tag's.

The file formats it reads are public: [MS-XLS], [MS-XLSB] and [MS-CFB] from Microsoft's Open Specifications, ECMA-376 (SpreadsheetML) and OASIS OpenDocument 1.2/1.3.

## Extraction

- `/app/reference/calamine-0.37.0` is the published crate, unchanged and read-only. The task is to port its readers to Go. There is no Rust toolchain in the image.
- `/app/calamine-go` is a new Go module: a stub `cmd/xlsdump` and `golang.org/x/text` v0.42.0 vendored from the Go module proxy (BSD-3-Clause).
- The JSON dump is defined by this task. It prints what calamine's public API returns with the crate's `picture` feature enabled (`sheets_metadata`, `worksheet_range`, `worksheet_formula`, `defined_names`, `merge_cells_by_sheet_name`, `hyperlinks_by_sheet_name`, `workbook_properties`, `vba_project`, `pictures_with_metadata`, `table_by_name` and `pivot_table_data`). Every expected output was produced by calamine 0.37.0 itself: a small Rust program prints the same JSON through the crate's API, built with Rust 1.91 and run in a container without network. Two full runs gave identical output.
- Inputs: 135 workbooks from the repository's `tests/` directory that calamine can open (66 ship as samples and 69 are hidden; one 18 MB file was left out), plus 864 generated workbooks (108 samples, 756 hidden, of which 747 are scored). The generated ones come from random workbook specifications rendered by XlsxWriter 3.2.0, openpyxl 3.1.5, xlwt 1.3.0, LibreOffice 7.4 (Debian bookworm, formulas recalculated on load), and by hand-written SpreadsheetML, BIFF12, OpenDocument, BIFF5 and BIFF8/CFB writers that follow the specifications above. Files that calamine cannot open, or that it panics on, are not scored.
- The reference solution is a Go port of the same readers written for this task: about 8,000 lines covering CFB, BIFF2-8 records and formula decoding, SpreadsheetML with shared-formula expansion, BIFF12, OpenDocument, VBA projects (MS-OVBA decompression and the dir stream), OfficeArt and DrawingML pictures, tables, pivot caches, hyperlinks and document properties. It reproduces all 5,797 scored units of the 816 hidden workbooks and all 1,133 units of the samples.

## Why it is real work

Moving a file-format library from one language to another is ordinary engineering work. A Go service that ingests uploaded spreadsheets either links a C or Rust library through cgo, with the build and deployment costs that brings, or reimplements the readers. A reimplementation has to match the library its users already trust, down to the details: which number formats count as dates, how shared formulas and code pages decode, how legacy BIFF formula tokens turn into text. Doing that means reading about 8,000 lines of Rust across four container formats and checking the port against real files, one format and one edge case at a time.
