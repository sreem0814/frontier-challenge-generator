# Rebuild the FlatBuffers schema compiler front end

`/app` is FlatBuffers v25.12.19 (commit `7e16302`), trimmed to the C++ headers, the `flatc` sources, their CMake build, `reflection/reflection.fbs` and the format documentation. One file was replaced by a stub: `src/idl_parser.cpp`, the compiler's whole front end. Upstream it holds:

- the `.fbs` schema parser (tokenizer, namespaces, includes, enums and bit flags, unions, structs with fixed arrays and alignment, tables with ids, defaults, optional scalars and every built-in attribute, `rpc_service`, `root_type`, `file_identifier`, `file_extension`, user attributes, doc comments, per-language feature checks, warnings and error messages);
- the `.proto` parser behind `flatc --proto` (proto2 and proto3, nested types, `oneof`, `map`, options, imports, field ids);
- the JSON data parser that turns JSON into a FlatBuffer under a schema (scalar conversion and range checks, enums by name and bit-flag lists, structs, fixed arrays, vectors, unions and union vectors, nested FlatBuffers, `flexbuffer` fields, `--force-defaults`, `--unknown-json`, size prefixes, key sorting), and schema-less JSON to FlexBuffers;
- `Parser::Serialize()`, which writes the binary schema (`.bfbs`, see `reflection/reflection.fbs`), and `Parser::Deserialize()`, which loads one back so `flatc` can generate code or parse JSON from a `.bfbs` file;
- `Parser::ConformTo()`, the schema evolution check behind `flatc --conform`;
- the helpers `idl.h` declares and the rest of `flatc` links against (`EnumDef` lookups, `Namespace::GetFullyQualifiedName`, `Parser::LookupStruct`, `SetRootType`, `MarkGenerated`, `GetIncludedFiles*`, `FLATBUFFERS_VERSION`).

The stub defines just enough symbols for `flatc` to link; every entry point fails. Your job is to write `src/idl_parser.cpp` again so that `flatc` behaves exactly like upstream v25.12.19: the same output files byte for byte, the same exit status, and the same warnings and error messages. Nothing else is graded.

## Workspace

- `/app/src/idl_parser.cpp`: the deliverable. Everything goes into this one file.
- `/app/include/flatbuffers/idl.h`: the interface (`Parser`, `IDLOptions`, `Type`, `FieldDef`, `StructDef`, `EnumDef`, `EnumVal`, `ServiceDef`, `RPCCall`, `Namespace`, `SymbolTable`, `CheckedError`), including the declarations of the parser's private methods. It is fixed: the grader compiles your file against a pristine copy, so editing a header only breaks your build.
- `/app/src/flatc.cpp`, `/app/src/flatc_main.cpp`: the command line driver. They show which `Parser` calls each option makes and how errors are printed.
- `/app/src/idl_gen_*.cpp`, `/app/src/bfbs_gen_*.cpp`, `/app/grpc/src/compiler/`: the code generators. They read the parser's in-memory model (field order, offsets, padding, attributes, doc comments, namespaces, which file declared what), so they are the most precise description of what your parser must build. `idl_gen_text.cpp` prints binaries as JSON, `idl_gen_fbs.cpp` prints a parsed `.proto` as `.fbs`, `binary_annotator.cpp` annotates binaries using the binary schema.
- `/app/include/flatbuffers/reflection_generated.h` and `/app/reflection/reflection.fbs`: the binary schema format.
- `/app/docs/source/*.md`: upstream documentation (schema language, grammar, `flatc` options, evolution rules, the binary schema, FlexBuffers). Where it and the samples disagree, the samples are right.
- `/app/build.sh`: configures (once) and builds `flatc` into `/app/build/flatc` with the options the grader uses (CMake, Ninja, Release, gcc 12, no tests). Incremental after the first run; a full build takes about a minute.
- `/app/check/selfcheck.py`, `/app/check/samples/`: 381 sample cases with the reference results, and the self-check that scores them. `/app/check/fbcase.py` is the transcript code the grader uses (its own copy).
- `/usr/src/flatbuffers-base`: a read-only pristine copy of the starting tree. The grader verifies it file by file; do not touch it.
- Toolchain: Debian 12's gcc 12, CMake 3.25, Ninja, gdb; Python 3.11 for the self-check. There is no network and no other FlatBuffers implementation on the machine.

## What the grader does

1. Copies `/usr/src/flatbuffers-base`, replaces the stub with your `/app/src/idl_parser.cpp` (a regular file under 8 MiB; a missing one keeps the stub) and builds `flatc` with the same CMake options as `build.sh`, as an unprivileged user, with up to 40 minutes for the build.
2. Runs about 3,100 hidden cases. A case is a set of input files written into an empty directory and one `flatc` command line run there as an unprivileged user, with a 20 second limit, a 4 GiB address-space limit and a 64 MiB output-file limit. Outputs go to `./out` (`-o out`).
3. Reduces each run to a transcript and compares it with the transcript of upstream `flatc` on the same case. A case passes only when the transcripts are identical. The transcript is (see `check/fbcase.py`):
   - `status ok` (exit status 0) or `status fail` (any other exit status, a signal or a timeout);
   - in the buckets marked "messages" below: everything `flatc` printed on stdout and on stderr, with the absolute case directory replaced by `@`;
   - every file under `./out` with its relative path and the SHA-256 of its bytes (when the run succeeded, or always in the "messages" buckets).

The hidden cases are generated the same way as the samples, from different random seeds: random multi-file schemas (namespaces, includes, every type kind and attribute), upstream's own test schemas, random JSON documents for them, random `.proto` files, schema pairs for the evolution check, and damaged schemas, JSON and protos. No hidden input file appears in the samples.

## Buckets

| Bucket | Weight | Command lines | Compared |
| --- | --- | --- | --- |
| `schema_bfbs` | 0.08 | `-b --schema` on valid schemas, with `--bfbs-comments`, `--bfbs-builtins`, `--bfbs-filenames .` | status, output files (the `.bfbs` bytes) |
| `schema_model` | 0.06 | the same runs as `schema_bfbs` | the decoded content of the `.bfbs` (`check/bfbsdec.py`: every table and field of `reflection.fbs`, defaults applied), so a binary schema with the right content but a different byte layout still passes |
| `codegen` | 0.14 | `--cpp`, `--python`, `--rust`, `--ts`, `--go`, `--java`, `--csharp`, `--swift`, `--dart`, `--kotlin`, `--kotlin-kmp`, `--php`, `--lobster`, `--nim`, `--jsonschema`, with generator options and `--grpc` | status, every generated file |
| `json_binary` | 0.18 | `-b schema.fbs data.json` with `--strict-json`, `--force-defaults`, `--size-prefixed`, `--unknown-json`, `--allow-non-utf8`, `--natural-utf8`, `--root-type`; `-b --flexbuffers` | status, the binary bytes |
| `json_text` | 0.08 | `--json` from binaries (`--raw-binary`, `--size-prefixed`) and from JSON, with `--strict-json`, `--defaults-json`, `--natural-utf8`, `--json-nested-bytes`; `--annotate` | status, the output text |
| `diag` | 0.20 | any of the above on input that upstream rejects or warns about: damaged schemas and JSON, features a chosen language does not support, `--warnings-as-errors`, `--require-explicit-ids` | status, messages, output files |
| `proto` | 0.10 | `--proto` with `--oneof-union`, `--keep-proto-id`, `--proto-id-gap`, `--proto-namespace-suffix`, `--gen-all` | status, messages, the generated `.fbs` |
| `bfbs_input` | 0.08 | code generation, `-b --schema` and JSON parsing with a `.bfbs` file (written by upstream) as the schema | status, output files |
| `conform` | 0.08 | `--conform base.fbs new.fbs` and `--conform base.bfbs new.fbs` | status, messages |

Which bucket a case belongs to was fixed when the hidden set was generated: a case whose command line upstream rejects counts in `diag`. Each sample's `cmd.json` names its bucket.

## Reward

```
reward = sum over buckets b of  weight_b * passed_b / total_b
```

with the weights above (they sum to 1). The denominators are fixed by the hidden set; a crash, a timeout or a missing output fails the case. Upstream's `idl_parser.cpp` passes every case and scores exactly 1.0; the stub scores exactly 0.

Hard gates, each of which sets the reward to 0:

- `flatc` does not build from the pristine tree plus your `src/idl_parser.cpp`;
- `/usr/src/flatbuffers-base` differs from its original contents;
- system files the grader relies on were modified (the Python interpreter and libraries, the compiler, binutils, CMake, Ninja, make, libc, `/etc/ld.so.preload`, `/etc/ld.so.conf.d`).

Self-check for the build gate: `./build.sh`. Self-check for the score: `python3 check/selfcheck.py` prints each bucket's sample pass count and the weighted estimate; `--fails 20` lists failing ids, `--case ID` runs one case, prints what `flatc` printed and diffs the transcript against the expected one (the expected files are in `check/samples/ID/expected/`), and `--bucket NAME` runs one bucket.

## Behaviour notes

The samples are the final word; these are the places where a careful reimplementation most often differs.

- Error and warning text: `flatc` prints the parser's `error_` string. Each message carries the absolute path of the file being parsed, the line and the column, as `Parser::Message` would build it, and the parser stops at the first error. Warnings (for example on field names that are not snake_case) accumulate before it.
- Table layout: field ids come from declaration order or from `id` attributes (a union takes two ids), vtable offsets follow from the ids, and `struct` fields get offsets, padding and alignment from their types and `force_align`.
- The binary schema lists objects, enums, fields and services sorted by name; attributes, documentation, `declaration_file` and `fbs_files` appear only where upstream writes them (`--bfbs-comments`, `--bfbs-builtins`, `--bfbs-filenames`). Default values are stored as `default_integer` or `default_real` by type.
- JSON to binary: the builder calls determine the bytes, so field serialization order, alignment padding, vector and string placement, deduplication and key sorting all have to match upstream.
- `--proto` output is printed by `idl_gen_fbs.cpp` from what your parser builds, including the namespaces, the converted names and the unions made from `oneof`.

## Constraints

- Write C++ that builds with the shipped toolchain and the existing CMake build (the project's C++ standard and libraries). New source files are not picked up; the grader takes only `src/idl_parser.cpp`.
- The upstream implementation is not on this machine and there is no network. Work from `idl.h`, the driver, the generators, the documentation and the samples.
- Changes under `/app/check` or anywhere else in `/app` only affect your own runs.

## Time budget

You have 20 hours. A timer daemon writes the real remaining budget to `/app/.timer/remaining_secs` (and `elapsed_secs`); the files `alert_30min`, `alert_10min` and `alert_5min` appear there as the budget runs down. The container clock says nothing about your budget: run `cat /app/.timer/remaining_secs` before long steps and plan the session against it.

## Working rules

Nobody will answer questions; decide and keep going. The parser is large, so build it in layers that each make whole buckets pass, and keep `./build.sh` green between layers: a file that does not compile scores 0, a partial parser scores what it passes. Run `python3 check/selfcheck.py` after every meaningful change, take the failing samples one at a time with `--case`, and back out changes that lose more cases than they win. The hidden set is eight times larger than the samples and drawn from the same generators, so fix the rule behind a failure rather than the single case. Commit to git in `/app` as you go, and leave the last 20 minutes for a clean `./build.sh clean && ./build.sh` and a final self-check.
