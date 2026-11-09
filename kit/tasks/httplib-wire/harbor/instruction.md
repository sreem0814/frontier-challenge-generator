# Rebuild the HTTP/1.1 message layer of cpp-httplib

`/app/httplib.h` is cpp-httplib 0.62.0, the header-only C++ HTTP server and client library, with its HTTP/1.1 message layer taken out. The sockets, thread pool, routing, TLS glue, WebSocket and SSE code, compression back ends and the public API are all still there, but the code that reads and writes HTTP messages is gone: 90 function bodies and the body of the `FormDataParser` class are replaced by stubs marked `/* removed from this tree */`. As shipped, the server cannot parse a request and the client cannot read a response. Your job is to bring the layer back so that the library behaves exactly like the released 0.62.0 header: the same parse results, the same status codes for malformed input, the same bytes on the wire.

## Workspace

- `/app/httplib.h`: the library. The only graded file. A git repository with one commit (the starting point) lives in `/app`.
- `/app/docs/`: the upstream `README.md`, `README-stream.md`, `README-sse.md`, `README-websocket.md` and the user guide (`docs/guide/`). They describe the public behaviour (ranges, multipart forms, content receivers, redirects, compression, limits).
- `/app/example/`: the upstream example programs.
- `/app/tools/probe.cc`, `/app/tools/server.cc`: the two programs the grader builds against your header (described below).
- `/app/tools/wire.py`: how the grader drives them and compares results. `/app/tools/selfcheck.py`: builds both against `/app/httplib.h` and scores the samples.
- `/app/samples/cases.jsonl.gz`: 4,546 sample cases with their expected results.
- `/app/README.txt`: this map in short.

GCC 12, the zlib, brotli and zstd development packages, gdb and Python 3 are installed. There is no network and no TLS library.

## What was removed

Every declaration, signature, class layout (except `FormDataParser`'s private part) and comment outside the removed bodies is unchanged. The stubs return failure or empty values; `range_error` returns "no error". The removed code falls into six areas, which the grader also uses to group its cases:

- **H, messages**: `stream_line_reader::getline` and `append`, `parse_header`, `parse_trailers`, `read_headers`, `parse_status_line`, `read_response_head`, the `fields::` validators (`is_token_char`, `is_token`, `is_field_name`, `is_vchar`, `is_obs_text`, `is_field_vchar`, `is_field_content`, `is_field_value`, `is_field_valid`, `is_request_target`, `is_host`), `has_conflicting_content_length`, `is_chunked_transfer_encoding`, `Server::parse_request_line`, `ClientImpl::read_response_line`, `write_request_line`, `write_response_line`, `write_headers`.
- **B, bodies**: `read_content_with_length`, `read_content_without_length`, `read_content_chunked`, `prepare_content_receiver`, `read_content`, `Server::read_content`, `Server::read_content_core`, `ChunkedDecoder::read_payload`, `ChunkedDecoder::parse_trailers_into`, `BodyReader::read`, `write_content_with_progress`, `write_content_without_length`, `write_content_chunked`, `set_framing_headers`.
- **Q, URLs and queries**: `parse_url`, `resolve_relative_location`, `encode_path`, `params_to_query_str`, `divide_query_pair`, `parse_query_text`, `normalize_query_string`, `encode_request_target`, `encode_uri_component`, `encode_uri`, `decode_uri_component`, `decode_uri`, `encode_path_component`, `decode_path_component`, `encode_query_component`, `decode_query_component`, `append_query_params`.
- **M, multipart**: the `FormDataParser` class (streaming multipart/form-data parser: `set_boundary`, `is_valid`, `parse`), `parse_multipart_boundary`, `parse_disposition_params`, `is_multipart_boundary_chars_valid`, `escape_multipart_field`, `serialize_multipart_formdata_item_begin`, `serialize_multipart_formdata_item_end`, `serialize_multipart_formdata_finish`, `serialize_multipart_formdata`, `get_multipart_content_length`, `make_multipart_content_provider`, `sanitize_filename`.
- **R, ranges**: `parse_range_header`, `coalesce_ranges`, `range_error`, `get_range_offset_and_length`, `make_content_range_header_field`, `process_multipart_ranges_data`, `make_multipart_ranges_data`, `get_multipart_ranges_data_length`, `write_multipart_ranges_data`, `Server::apply_ranges`, `Server::check_if_range`, `make_range_header`.
- **N, negotiation**: `extract_media_type`, `parse_quality`, `encoding_type` (the `Request`, content-type overload), `remove_quoted_strings`, `parse_accept_header`, `unescape_quoted_pairs`, `escape_quoted_pairs`, `parse_www_authenticate`, `Server::check_if_not_modified`.

You may restructure freely: add helpers, members or classes, change the private part of any class, and rewrite code outside the stubs. The interface is fixed: every function and class declared in the starting header must keep its name, namespace and signature, because the grader's programs and the upstream test suite call public functions and many `detail::` ones directly. Keep the library header-only and self-contained in this one file.

## How grading works

Only `/app/httplib.h` is graded. It is copied alone into an empty directory, so it must not include other files from `/app`. Everything below is compiled and run as a different unprivileged user, with no network, against that copy.

**Build gate.** `probe.cc` and `server.cc` (the files in `/app/tools/`) are compiled with

    g++ -std=c++17 -O1 -I<dir> -DCPPHTTPLIB_ZLIB_SUPPORT -DCPPHTTPLIB_BROTLI_SUPPORT -DCPPHTTPLIB_ZSTD_SUPPORT \
        <file>.cc -o <file> -lz -lbrotlicommon -lbrotlienc -lbrotlidec -lzstd -lpthread

If either fails to compile or link, the score is 0.

**Cases.** 14,044 frozen cases, each with an expected result produced by the released 0.62.0 header through the same programs. A case passes when its result is byte-identical to the expected one.

- *Library cases* run through `probe`, one case per input line, one result line per case. Each names an operation (`hdr`, `fields`, `status`, `readhdr`, `lines`, `resphead`, `te`, `chunk`, `content`, `bodyreader`, `url`, `relloc`, `enc`, `query`, `append`, `boundary`, `dispo`, `form`, `mpser`, `range`, `rangehdr`, `mranges`, `accept`, `media`, `quality`, `encoding`, `wwwauth`); `probe.cc` shows exactly which functions each one calls and how the result is printed. `form` feeds the multipart parser in the listed piece sizes and merges adjacent data callbacks, so the result does not depend on how you split data internally.
- *Client cases* (`cli`) run an `httplib::Client` against a scripted peer inside `probe`: the peer answers each accepted connection with scripted bytes and records the request bytes. The result holds the client's error, status, version, reason, headers, body, trailers, redirect location and every request the peer received, so the request line, header order, encoding of paths and queries, chunked uploads and multipart uploads must match too.
- *Server cases* send raw bytes to `server` (one TCP connection per case, port numbers are the grader's) followed by `GET /end HTTP/1.1` with `Connection: close`, and record everything the server writes until it closes the connection. The response bytes are compared after the random `multipart/byteranges` boundary is replaced by `BOUNDARY`. `server.cc` lists its routes: request echo, fixed data, content providers with and without a length, chunked providers with trailers, a content-reader endpoint for streaming multipart, a static mount with fixed file times, compression by `Accept-Encoding`, `Accept` parsing.

Each case belongs to one area (H, B, Q, M, R or N) and to a family of related inputs (a valid input and variants of it). When the expected result is a rejection (a failed parse, an error status of 400 or higher, a client error), the case is credited only if at least one non-rejection case of the same family also passes; this keeps a reject-everything shortcut from collecting credit. A crash, a hang (20 s for a `probe` case, 6 s for a server exchange) or a missing result fails the case and the run continues with the next one.

**Upstream tests.** The 716 tests of cpp-httplib 0.62.0's own `test/test.cc` that pass with the released header and fail with the starting one. The suite is compiled against your header with `-std=c++17 -O0` and the same three defines (it uses GoogleTest; tests that need the internet are not included). Each test runs as its own process (`--gtest_filter=<name>`), eight at a time, 20 seconds each, and passes when it exits 0 with GoogleTest reporting one passed test. If the suite does not compile against your header, this part scores 0 but the rest still counts; the usual cause is a changed or missing declaration. A few extra tests that must fail are added under realistic names; if any of them reports success, the run counts as tampered and scores 0.

## Scoring

    upstream = (upstream tests passed) / 716
    area_X   = (credited cases of area X) / (cases of area X)     for X in H, B, Q, M, R, N
    reward   = 0.3 * upstream + 0.7 * (area_H + area_B + area_Q + area_M + area_R + area_N) / 6

Hard gates (score 0): the build gate above, and the anti-tamper check. All denominators are fixed. The starting header scores exactly 0 and the released header scores 1. The six areas weigh the same, so the smaller areas (ranges, negotiation) are worth as much as the bodies area with its thousands of cases; the area sizes are H 1,874, B 4,389, Q 2,268, M 2,430, R 1,382, N 1,701.

## Checking your work

    python3 /app/tools/selfcheck.py                          # build gate + all samples, per-area credit and estimate
    python3 /app/tools/selfcheck.py --area R --show 5        # failing range cases with input, expected and actual
    python3 /app/tools/selfcheck.py --op form --show 3

The self-check uses the same programs, flags, comparison and family rule as the graded run, on the sample cases, and prints the case part of the formula; it cannot run the upstream suite, which is not in the image. A full run takes about a minute. The samples come from the same generators as the graded cases but with other inputs, so build to the behaviour, not to the sample inputs. Write your own small programs against `/app/httplib.h` (the examples and docs show the API) to exercise clients and servers end to end; the upstream suite tests things like keep-alive, `Expect: 100-continue`, payload limits, redirects, streaming content receivers, `open_stream` and static files through real sockets on localhost.

## Time budget

You have 8 hours. The real remaining time is in `/app/.timer/remaining_secs`; the system clock tells you nothing about it. `cat` it before long builds and test runs. `alert_30min`, `alert_10min` and `alert_5min` appear in `/app/.timer/` as the end nears.

## Constraints

- Work as the `agent` user in `/app`. No network; everything you need is installed.
- Only `/app/httplib.h` counts, and only as a single self-contained header. Nothing else in `/app` exists at grading time.
- The grader compiles your header itself; do not depend on anything you built in the image.
- Keep cases fast: a case that takes longer than its timeout fails.

## Operating rules

Nobody will answer questions; decide and keep going. The header must compile at every commit, because a compile error is the one thing that zeroes everything, while a half-finished function only loses its own cases. The request and response paths come first since every server and client case runs through them, but each area carries a sixth of the case part on its own, so do not leave ranges, multipart or negotiation for the last half hour. Run the self-check often, look at the failing cases it shows, commit what works, and revert experiments that lower the score. Check the timer before long runs and keep the last stretch for a final self-check on a clean build.
