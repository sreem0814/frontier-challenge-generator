/app: cpp-httplib v0.62.0 (MIT, LICENSE) with its HTTP/1.1 message layer taken out.

httplib.h            the library, header-only. 90 function bodies (and the FormDataParser class body) are replaced
                     by stubs marked /* removed from this tree */; every declaration and signature is unchanged.
                     This is the only file that is graded.
docs/                upstream README.md, README-stream.md, README-sse.md, README-websocket.md and the user guide (guide/)
example/             upstream example programs (they use the public API)
tools/probe.cc       the library/client case program the grader builds against httplib.h
tools/server.cc      the HTTP server the grader builds against httplib.h and sends raw requests to
tools/wire.py        how the grader drives both programs and compares results
tools/selfcheck.py   builds both programs against /app/httplib.h and scores the sample cases
samples/cases.jsonl.gz  4,546 sample cases with expected results
timer.sh, .timer/    the task timer (see the task description)

Build flags used for grading: g++ -std=c++17 -DCPPHTTPLIB_ZLIB_SUPPORT -DCPPHTTPLIB_BROTLI_SUPPORT
-DCPPHTTPLIB_ZSTD_SUPPORT ... -lz -lbrotlicommon -lbrotlienc -lbrotlidec -lzstd -lpthread (no TLS).
