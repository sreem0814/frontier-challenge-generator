# Provenance

## Source
Fluent Bit (https://github.com/fluent/fluent-bit, Apache-2.0) at commit f4739648c0e91337331765edb9bd19da5a7a1a52, and its issue #4651, "modify filter not working with record accessor" (opened 2022-01-21, still open with no linked pull request). A maintainer confirmed in the issue that the modify filter's rules do not support record-accessor keys; only conditions take them, and those fail on array indexes.

## Extraction
The environment ships the upstream tree at that commit as `git archive` output, unchanged, in a fresh one-commit repository, pre-built with a trimmed plugin set (no WASM, LuaJIT, Kafka or examples). Nothing was removed: the record-accessor library and the other filters that use it are part of the starting tree. The feature specification in instruction.md was written for this task, keeping every existing plain-key behaviour of the filter. The reference implementation is our own C patch to the filter and the record-accessor code. The graded cases are generated configurations and records; their expected outputs were frozen from an executable model of the specification whose plain-key part was checked against the starting tree on 1,000 cases, and only cases the starting tree gets wrong were kept (plain-key regression cases are the exception: the starting tree passes them).

## Why it is real work
Log pipelines routinely carry nested records (Kubernetes metadata, OpenTelemetry attributes, JSON payloads). Operators who want to redact, rename or relocate a nested field with the modify filter hit exactly this gap and today fall back to Lua scripts or chains of nest filters. Closing it means extending a mature C plugin and its msgpack record-accessor layer without breaking existing configurations.
