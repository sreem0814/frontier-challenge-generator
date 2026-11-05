# Restore the Matter TLV codec and its consumers in connectedhomeip

`/app` is a trimmed copy of connectedhomeip (the Matter SDK) at release v1.6.1.0. The implementations of four components were removed and replaced with stubs that compile but do nothing useful: every function returns `CHIP_ERROR_NOT_IMPLEMENTED`, `false`, zero or an empty value. The headers are unchanged. Your job is to write the implementations back so the library behaves exactly like upstream v1.6.1.0: the same bytes on encode, the same values on decode, and the same `CHIP_ERROR` code on every failure path, including malformed and truncated input.

The four components, in dependency order:

1. **TLV codec** (`src/lib/core`): `TLVReader` (including `ContiguousBufferTLVReader` and reading through a `TLVBackingStore`), `TLVWriter` (including backing-store output, `PutStringF`, reserve/unreserve, `PutPreEncodedContainer`, `CopyElement`, `CopyContainer`), tag formatting (`Tag::AppendTo`), `TLV::Utilities` (`Iterate`, `Count`, `Find`), `TLVUpdater`, `TLVCircularBuffer` with `CircularTLVReader`/`CircularTLVWriter` and eviction, `TlvVectorWriter`, and `TLV::Debug` (`Dump`, `DecodeType`, `DecodeTagControl`).
2. **Message framing** (`src/transport/raw/MessageHeader.cpp`): `PacketHeader` and `PayloadHeader` encode, decode and size computation, and `MessageAuthenticationCode` encode/decode.
3. **Onboarding payloads** (`src/setup_payload`): Base38 encode/decode, the QR-code payload generator and parser (including the optional TLV data: vendor elements, serial number, extension data, multi-payload `*` concatenation), the manual pairing code generator and parser, `SetupPayload`/`PayloadContents` validation and optional-data management, `SetupPayload::FromStringRepresentation`, and `AdditionalDataPayloadParser`.
4. **JSON <-> TLV** (`src/lib/support/jsontlv`): `TlvToJson`, `JsonToTlv`, `ConvertTlvTag`, the older `TlvJson.cpp` converter (`TlvToJson(reader, Json::Value&)`, `JsonToString`) and `PrettyPrintJsonString`. The JSON format is documented in `src/lib/support/jsontlv/README.md`.

The TLV encoding is Matter Core Specification Appendix A; the onboarding payload layouts are Matter Core Specification section 5.1. No copy of the specification is in the image and there is no network access. The header files document most behaviour, including many of the error codes; where a header is silent, upstream v1.6.1.0 behaviour is the target.

## Workspace

```
/app
  CMakeLists.txt          builds build/libchipcore.a; compiles every .cpp in the four component directories
  build.sh                ./build.sh (incremental) or ./build.sh clean
  src/lib/core/           TLV*.h (contract) and TLV*.cpp (stubs: yours to write); CHIPError, support headers
  src/transport/raw/      MessageHeader.h (contract), MessageHeader.cpp (stub)
  src/setup_payload/      headers (contract) and stubbed .cpp files
  src/lib/support/jsontlv/ headers, README.md (format), stubbed .cpp files
  src/lib/support/, src/system/, src/protocols/, config/, third_party/, shim/   support code, read-only for grading
  check/
    case_runner.cpp       the driver the grader uses: reads case scripts, calls the library, prints transcripts
    CMakeLists.txt        builds case_runner against the tree given as -DTREE
    selfcheck.py          builds everything, runs the sample cases, compares transcripts, prints a score estimate
    samples/cases.txt     439 sample cases (six buckets)
    samples/expected.txt  the upstream transcripts for those cases
/usr/src/chip-base        the untouched starting tree (read-only reference copy; do not modify)
```

`/app` is a git repository with one commit (the starting state). Commit as you like.

## What to deliver

Implement these files (stubs today), most important first:

- `src/lib/core/TLVReader.cpp`, `TLVWriter.cpp`, `TLVTags.cpp`, `TLVUtilities.cpp`, `TLVUpdater.cpp`, `TLVCircularBuffer.cpp`, `TLVDebug.cpp`, `TLVVectorWriter.cpp`
- `src/setup_payload/QRCodeSetupPayloadParser.cpp`, `QRCodeSetupPayloadGenerator.cpp`, `SetupPayload.cpp`, `ManualSetupPayloadParser.cpp`, `ManualSetupPayloadGenerator.cpp`, `Base38Encode.cpp`, `Base38Decode.cpp`, `AdditionalDataPayloadParser.cpp`
- `src/lib/support/jsontlv/TlvToJson.cpp`, `JsonToTlv.cpp`, `TlvJson.cpp`, `TextFormat.cpp`
- `src/transport/raw/MessageHeader.cpp`

Interface rules:

- The public API is the shipped headers. `check/case_runner.cpp` is compiled against your tree and calls that API directly, so every public signature it uses must keep compiling with the same meaning.
- The grader takes from `/app` only these files: in `src/lib/core`, files named `TLV*.cpp` / `TLV*.h`; in `src/transport/raw`, `MessageHeader.cpp` / `MessageHeader.h`; every `.cpp` / `.h` directly in `src/setup_payload` and `src/lib/support/jsontlv`; and any new source file (`.cpp .cc .h .hpp .inc .ipp`) you add directly in one of those four directories. You may change those headers (for example to add private members or helpers) as long as `case_runner.cpp` still compiles and behaves the same. Everything else (CMakeLists.txt, support code, `check/`) comes from the starting tree, so edits there have no effect on grading.
- Build options are fixed by the shipped CMakeLists.txt: C++17 (GNU extensions), `CHIP_CONFIG_TLV_VALIDATE_CHAR_STRING_ON_WRITE=1`, logging off, malloc-based `Platform::Memory`. Use only the C++ standard library, jsoncpp and the code in the tree.

## How behaviour is checked

`check/case_runner.cpp` reads case scripts (`CASE <id> <bucket>`, one operation per line, `END`) and runs each case in its own forked process (10 s limit, 1 GiB address space). Every operation prints the `CHIP_ERROR` it returned (`e=<hex AsInteger()>`) and every value it produced: encoded bytes as hex, decoded values for every typed getter, tags through `Tag::AppendTo`, lengths and positions, Debug::Dump text, generated QR and manual codes, JSON text. A case passes when its whole transcript is byte-identical to the transcript upstream v1.6.1.0 produces. Read `case_runner.cpp` for exactly which API calls each operation makes.

The six buckets:

| bucket | what the cases exercise |
| --- | --- |
| tlv_write | writer programs into fixed buffers (including too-small ones), chunked backing stores and vectors; every scalar width, preserve-size puts, strings with invalid UTF-8, nested containers via StartContainer and OpenContainer, pre-encoded containers, PutStringF, reserve; then the output is walked by the reader |
| tlv_read | readers over valid, non-minimal, mutated and truncated encodings, plain, contiguous and chunked; full walks calling every typed getter, and explicit sequences of Next/Expect/Enter/Exit/Open/Close/Skip/Find/Count/GetBytes/GetString/DupBytes/DupString/GetDataPtr |
| tlv_tools | Utilities Count/Find/Iterate, Debug::Dump, TLVUpdater edit sequences, CopyElement/CopyContainer, circular buffers with eviction callbacks |
| msg_header | packet and payload header encode/decode (all flag combinations, short buffers, mutated input), MIC handling |
| json_tlv | TLV to JSON, JSON to TLV (valid and malformed JSON, small buffers), ConvertTlvTag, the older converter, pretty printing |
| onboarding | QR and manual code generation and parsing (valid, invalid and corrupted strings), Base38, optional data, validation, multi-payload strings, additional-data payloads |

The grader runs about 3,650 cases you cannot see, generated the same way as the samples but with different inputs. The samples are representative, not exhaustive: a change that passes every sample can still fail hidden cases.

## Building and checking

```
cd /app && ./build.sh                    # the library alone
python3 check/selfcheck.py               # builds case_runner against /app, runs the samples, prints per-bucket results
python3 check/selfcheck.py --bucket tlv_read --show 3     # diffs of the first failing cases in a bucket
python3 check/selfcheck.py --case s00042                  # one case: expected vs actual transcript
python3 check/selfcheck.py --cases mine.txt               # run your own case script and print transcripts
```

`/usr/src/chip-base` holds the starting tree if you need to compare against it.

## Scoring

Grading copies the starting tree, overlays your component files from `/app`, builds `libchipcore.a` and its own copy of `case_runner` from scratch (as an unprivileged user, offline), and runs the hidden cases.

Hard gates (any failure scores exactly 0):

- the library or `case_runner` fails to build from the clean copy plus your files (self-check: `python3 check/selfcheck.py` builds the same way);
- the starting tree in `/usr/src/chip-base` or the system tools the grader relies on were modified.

Score: `reward = sum over buckets b of w_b * passed_b / total_b`, with weights tlv_write 0.14, tlv_read 0.16, tlv_tools 0.18, msg_header 0.10, json_tlv 0.18, onboarding 0.24. The denominators are fixed: a case that crashes, times out or prints anything different counts as failed. Upstream v1.6.1.0 passes every case, so a faithful implementation scores 1.0; the untouched stubs score 0. `selfcheck.py` prints the same weighted formula over the samples as an estimate.

## Time budget

You have 8 hours. Check `cat /app/.timer/remaining_secs` before long steps; `alert_30min` and `alert_10min` appear in `/app/.timer` as the budget runs down. The container clock does not tell you the budget.

## Constraints

- No network. Everything you need is in the image.
- Do not modify `/usr/src/chip-base`, the system compiler, Python or core system packages.
- Leave no background processes running when you finish.

## Working rules

Nobody will answer questions; decide and keep going. Keep `./build.sh` and `check/selfcheck.py` green at every commit: a stub that compiles scores what it passes, a tree that fails to build scores 0. The reader and writer underpin the updater, utilities, onboarding parser and JSON converter, so get them exact first, then spread out; every bucket pays, and the onboarding and JSON buckets weigh more than they look. Error paths are graded as strictly as success paths: when a header documents an error code, return that one. Check remaining time before big refactors and leave the last half hour for a clean build and a final self-check run.
