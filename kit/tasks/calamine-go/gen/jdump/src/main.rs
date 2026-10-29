// jdump: dump a workbook with calamine 0.37.0 into the JSON shape the task's CLI must produce.
// Usage: jdump <out_dir> <workbook>...   (writes <out_dir>/<basename>.json per workbook)
use calamine::{open_workbook_auto, Data, Dimensions, Range, Reader, SheetType, SheetVisible, Sheets};
use sha2::{Digest, Sha256};
use serde_json::{json, Map, Value};
use std::fs::File;
use std::io::{BufReader, Write};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::Path;

fn num(f: f64) -> Value {
    if f.is_nan() {
        json!("NaN")
    } else if f.is_infinite() {
        json!(if f > 0.0 { "inf" } else { "-inf" })
    } else {
        json!(f)
    }
}

fn cell_value(d: &Data) -> Vec<Value> {
    match d {
        Data::Int(i) => vec![json!("i"), json!(i)],
        Data::Float(f) => vec![json!("f"), num(*f)],
        Data::String(s) => vec![json!("s"), json!(s)],
        Data::Bool(b) => vec![json!("b"), json!(b)],
        Data::DateTime(dt) => {
            let (y, mo, d, h, mi, s, ms) = dt.to_ymd_hms_milli();
            vec![
                json!("d"),
                num(dt.as_f64()),
                json!(if dt.is_duration() { "timedelta" } else { "datetime" }),
                json!(format!("{y:04}-{mo:02}-{d:02}T{h:02}:{mi:02}:{s:02}.{ms:03}")),
            ]
        }
        Data::DateTimeIso(s) => vec![json!("di"), json!(s)],
        Data::DurationIso(s) => vec![json!("du"), json!(s)],
        Data::Error(e) => vec![json!("e"), json!(e.to_string())],
        Data::Empty => vec![],
    }
}

fn tagged(d: &Data) -> Value {
    let v = cell_value(d);
    if v.is_empty() {
        Value::Null
    } else {
        Value::Array(v)
    }
}

fn dims(d: &Dimensions) -> Value {
    json!([d.start.0, d.start.1, d.end.0, d.end.1])
}

fn opt(s: &Option<String>) -> Value {
    match s {
        Some(v) => json!(v),
        None => Value::Null,
    }
}

fn hex(b: &[u8]) -> String {
    let h = Sha256::digest(b);
    h.iter().map(|x| format!("{x:02x}")).collect()
}

fn dump_range(r: &Range<Data>) -> (Value, Value) {
    let dims = match (r.start(), r.end()) {
        (Some(s), Some(e)) => json!([s.0, s.1, e.0, e.1]),
        _ => Value::Null,
    };
    let (r0, c0) = r.start().unwrap_or((0, 0));
    let mut cells = Vec::new();
    for (row, col, v) in r.used_cells() {
        let mut c = vec![json!(r0 as usize + row), json!(c0 as usize + col)];
        let cv = cell_value(v);
        if cv.is_empty() {
            continue;
        }
        c.extend(cv);
        cells.push(Value::Array(c));
    }
    (dims, Value::Array(cells))
}

fn dump_formulas(r: &Range<String>) -> Value {
    let (r0, c0) = r.start().unwrap_or((0, 0));
    let mut out = Vec::new();
    for (row, col, v) in r.used_cells() {
        out.push(json!([r0 as usize + row, c0 as usize + col, v]));
    }
    Value::Array(out)
}

fn typ(t: SheetType) -> &'static str {
    match t {
        SheetType::WorkSheet => "worksheet",
        SheetType::DialogSheet => "dialogsheet",
        SheetType::MacroSheet => "macrosheet",
        SheetType::ChartSheet => "chartsheet",
        SheetType::Vba => "vba",
    }
}

fn vis(v: SheetVisible) -> &'static str {
    match v {
        SheetVisible::Visible => "visible",
        SheetVisible::Hidden => "hidden",
        SheetVisible::VeryHidden => "veryhidden",
    }
}

fn guard<T, F: FnOnce() -> Result<T, String>>(f: F) -> Result<T, String> {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(r) => r,
        Err(_) => Err("panic".to_string()),
    }
}

fn dump(path: &Path) -> Value {
    let wb = guard(|| open_workbook_auto(path).map_err(|e| e.to_string()));
    let mut wb: Sheets<BufReader<File>> = match wb {
        Ok(w) => w,
        Err(e) => return json!({ "error": "open", "detail": e }),
    };
    let fmt = match &wb {
        Sheets::Xls(_) => "xls",
        Sheets::Xlsx(_) => "xlsx",
        Sheets::Xlsb(_) => "xlsb",
        Sheets::Ods(_) => "ods",
    };
    let metas: Vec<_> = wb.sheets_metadata().to_vec();
    let names: Vec<Value> = wb
        .defined_names()
        .iter()
        .map(|(n, f)| json!([n, f]))
        .collect();
    let mut sheets = Vec::new();
    for m in metas {
        let mut s = Map::new();
        s.insert("name".into(), json!(m.name));
        s.insert("type".into(), json!(typ(m.typ)));
        s.insert("visible".into(), json!(vis(m.visible)));
        match guard(|| wb.worksheet_range(&m.name).map_err(|e| e.to_string())) {
            Ok(r) => {
                let (dims, cells) = dump_range(&r);
                s.insert("dims".into(), dims);
                s.insert("cells".into(), cells);
            }
            Err(_) => {
                s.insert("dims".into(), Value::Null);
                s.insert("cells".into(), json!("error"));
            }
        }
        match guard(|| wb.worksheet_formula(&m.name).map_err(|e| e.to_string())) {
            Ok(r) => {
                s.insert("formulas".into(), dump_formulas(&r));
            }
            Err(_) => {
                s.insert("formulas".into(), json!("error"));
            }
        }
        let merged = match &mut wb {
            Sheets::Xlsx(x) => Some(guard(|| {
                x.merge_cells_by_sheet_name(&m.name).map_err(|e| e.to_string())
            })),
            Sheets::Xls(x) => Some(guard(|| {
                x.merge_cells_by_sheet_name(&m.name).map_err(|e| e.to_string())
            })),
            _ => None,
        };
        match merged {
            Some(Ok(v)) => {
                let arr: Vec<Value> = v
                    .iter()
                    .map(|d| json!([d.start.0, d.start.1, d.end.0, d.end.1]))
                    .collect();
                s.insert("merged".into(), Value::Array(arr));
            }
            Some(Err(_)) => {
                s.insert("merged".into(), json!("error"));
            }
            None => {
                s.insert("merged".into(), Value::Null);
            }
        }
        let links = match &mut wb {
            Sheets::Xlsx(x) => Some(guard(|| {
                x.hyperlinks_by_sheet_name(&m.name).map_err(|e| e.to_string())
            })),
            _ => None,
        };
        match links {
            Some(Ok(v)) => {
                let arr: Vec<Value> = v
                    .iter()
                    .map(|h| {
                        json!([dims(&h.range), opt(&h.target), opt(&h.location), opt(&h.displayed_text), opt(&h.tooltip)])
                    })
                    .collect();
                s.insert("hyperlinks".into(), Value::Array(arr));
            }
            Some(Err(_)) => {
                s.insert("hyperlinks".into(), json!("error"));
            }
            None => {
                s.insert("hyperlinks".into(), Value::Null);
            }
        }
        sheets.push(Value::Object(s));
    }
    let mut out = Map::new();
    out.insert("format".into(), json!(fmt));
    out.insert("sheets".into(), Value::Array(sheets));
    out.insert("names".into(), Value::Array(names));
    // document properties (xlsx, xlsb)
    let props = match &mut wb {
        Sheets::Xlsx(_) | Sheets::Xlsb(_) => match guard(|| wb.workbook_properties().map_err(|e| e.to_string())) {
            Ok(p) => json!({
                "creator": opt(&p.creator), "last_modified_by": opt(&p.last_modified_by),
                "created": opt(&p.created), "modified": opt(&p.modified), "title": opt(&p.title),
                "subject": opt(&p.subject), "description": opt(&p.description), "keywords": opt(&p.keywords),
                "category": opt(&p.category), "content_status": opt(&p.content_status),
                "revision": opt(&p.revision), "version": opt(&p.version), "application": opt(&p.application),
                "app_version": opt(&p.app_version), "company": opt(&p.company), "template": opt(&p.template),
                "manager": opt(&p.manager)
            }),
            Err(_) => json!("error"),
        },
        _ => Value::Null,
    };
    out.insert("properties".into(), props);
    // VBA project
    let vba = match guard(|| wb.vba_project().map_err(|e| e.to_string())) {
        Ok(None) => Value::Null,
        Ok(Some(p)) => {
            let mut mods = Vec::new();
            for n in p.get_module_names() {
                match p.get_module(n) {
                    Ok(src) => mods.push(json!([n, src])),
                    Err(_) => mods.push(json!([n, "error"])),
                }
            }
            let refs: Vec<Value> = p
                .get_references()
                .iter()
                .map(|r| json!([r.name, r.description, r.path.to_string_lossy()]))
                .collect();
            json!({ "modules": mods, "references": refs })
        }
        Err(_) => json!("error"),
    };
    out.insert("vba".into(), vba);
    // pictures, sorted
    let mut pics: Vec<Value> = match &wb {
        Sheets::Xlsx(_) => wb
            .pictures_with_metadata()
            .iter()
            .map(|p| json!([p.sheet_name, p.row, p.col, p.extension, p.name, p.data.len(), hex(&p.data)]))
            .collect(),
        _ => wb
            .pictures()
            .unwrap_or_default()
            .iter()
            .map(|(ext, data)| json!(["", 0, 0, ext, "", data.len(), hex(data)]))
            .collect(),
    };
    pics.sort_by_key(|v| v.to_string());
    out.insert("pictures".into(), Value::Array(pics));
    // tables and pivot tables (xlsx)
    let (tables, pivots) = match &mut wb {
        Sheets::Xlsx(x) => {
            let tables = match guard(|| x.load_tables().map_err(|e| e.to_string())) {
                Ok(()) => {
                    let tnames: Vec<String> = x.table_names().iter().map(|s| s.to_string()).collect();
                    let mut arr = Vec::new();
                    for tn in tnames {
                        match guard(|| x.table_by_name(&tn).map_err(|e| e.to_string())) {
                            Ok(t) => {
                                let r = t.data();
                                let (d, cells) = dump_range(r);
                                arr.push(json!([t.name(), t.sheet_name(), t.columns(), d, cells]));
                            }
                            Err(_) => arr.push(json!([tn, "error"])),
                        }
                    }
                    Value::Array(arr)
                }
                Err(_) => json!("error"),
            };
            let pivots = match guard(|| x.pivot_tables().map_err(|e| e.to_string())) {
                Ok(pts) => {
                    let list: Vec<(String, String)> = pts
                        .get_pivot_tables_by_name_and_sheet()
                        .iter()
                        .map(|(s, n)| (s.to_string(), n.to_string()))
                        .collect();
                    let mut arr = Vec::new();
                    for (sh, nm) in list {
                        let rows = guard(|| {
                            let it = x.pivot_table_data(&pts, &sh, &nm).map_err(|e| e.to_string())?;
                            let mut rows = Vec::new();
                            for row in it {
                                let row = row.map_err(|e| e.to_string())?;
                                rows.push(Value::Array(row.iter().map(tagged).collect()));
                            }
                            Ok(rows)
                        });
                        match rows {
                            Ok(rows) => arr.push(json!([sh, nm, rows])),
                            Err(_) => arr.push(json!([sh, nm, "error"])),
                        }
                    }
                    Value::Array(arr)
                }
                Err(_) => json!("error"),
            };
            (tables, pivots)
        }
        _ => (Value::Null, Value::Null),
    };
    out.insert("tables".into(), tables);
    out.insert("pivots".into(), pivots);
    Value::Object(out)
}

fn main() {
    std::panic::set_hook(Box::new(|_| {}));
    let args: Vec<String> = std::env::args().collect();
    let out = Path::new(&args[1]);
    for p in &args[2..] {
        let path = Path::new(p);
        let v = dump(path);
        let name = format!("{}.json", path.file_name().unwrap().to_string_lossy());
        let mut f = File::create(out.join(name)).unwrap();
        serde_json::to_writer(&mut f, &v).unwrap();
        f.write_all(b"\n").unwrap();
    }
}
