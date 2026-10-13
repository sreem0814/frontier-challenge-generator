# CG

CG produces long-horizon software-engineering tasks for frontier coding agents. Its single source of truth is [capture/instructions.md](capture/instructions.md): the task format, the bar every task must meet, and how submissions are judged. That file is read-only on disk, and wherever another file disagrees with it, the spec wins.

This README is the manual for CG's idea pipeline, `cgpipe`, which finds task ideas and validates them in parallel.

## 1. How it works

**A validated idea** has passed all three of these:
- **V1:** a validator checked its facts at their sources and scored it above the line.
- **V2:** an independent judge re-scored it above the line.
- **Spike:** a feasibility run in a throwaway container built the reference and ran a sample of the grading surface. The results were deterministic and had real headroom over the untouched start.

The pipeline aims for as many validated ideas as possible, as fast as possible, at the lowest token cost:
- Everything plain code can do costs no tokens: harvesting sources, repo facts, the similarity screen, and a probe that builds each source and runs its tests.
- Model calls use the cheapest model that can do the job, run in safe mode with a cached system prompt, and pace themselves against live plan usage.

```
 harvest + enrich ─▶ data/sources.tsv ─▶ probe ─▶ write ─▶ L0 ─▶ V1 ─▶ V2 ─▶ spike ─▶ validated
 (GitHub API, no tokens)  (+ LLM scouts)   Docker    sonnet  script  haiku  opus   sonnet in Docker
                                           (no tokens: build + 3 test runs)  any stage can kill a seed (section 4)
```

One process, `pipeline/cgpipe.py`, runs the loop. Every 5 seconds it applies finished work to the state files and schedules new work, closest to the goal first:
1. spikes for `v2-pass` seeds, best score first (a seed whose source built first gets a fresh probe that keeps its build tree for the spike);
2. one judge call (V2) per batch whose seeds have all finished V1;
3. a probe for any seed that has no probe result yet, then V1;
4. enrichment of new source rows, the writer's next rows first;
5. probes of the source rows the writer would get next: each verdict moves its row up (green) or down (red), so the pick settles on rows that build and test;
6. the next batch of 10 cards, once every row in the pick is probed (or at least 12 of its rows are ready; the rest wait for the next batch), the previous batch has cleared L0, and fewer than 10 seeds wait for V1;
7. harvesting for channels that are due (every 24 h);
8. LLM scouts, only for classes whose unused rows can't cover the remaining batches.

At most 6 model calls run at once, with a pool limit per stage, and a call starts only if the budget still covers it plus the caps of every call in flight. Harvest, enrich and probes cost no tokens and don't count against that limit. Without `warmup`, the first batch waits until 12 rows of the writer's pick are probed (often 10-30 minutes, 2 probes at a time); after that, probes run ahead of the writer while V1 and V2 work.

## 2. Sources and channels

A channel is one distinct place real artifacts come from. Most channels have zero-token **harvesters**; the rest use an LLM **scout**. Queries are in pipeline/config.json.

| Channel | Class | Harvester |
|---|---|---|
| std-conformance | implementation | GitHub repo search: "conformance test suite", "test vectors", test-suite repos |
| lang-vm-suites | implementation | GitHub repo search: testsuite repos, assemblers |
| lib-testsuites | implementation | GitHub repo search: C, Go and Rust parsers, codecs, compression and formats with 500-5,000 stars |
| known-green-repos | implementation | SWE-smith environment profiles (MIT): about 600 C, C++, Go, JS/TS, Python and Rust repos whose test suites are known to run in a container. The profile files are parsed, never run; each row's notes carry the profile's test command, and the apt packages its Dockerfile installs become probe hints in data/hints.json |
| existing-ports | implementation | crates.io and npm "port of / pure Rust implementation", GitHub "port of" |
| diff-oracles | implementation | Homebrew's formula list (assemblers, formatters, converters, compilers, parsers ...) |
| oss-fuzz | implementation | OSS-Fuzz project list (sparse clone; contact emails are never read) |
| open-feature-issues | implementation | GitHub issue search: open enhancement issues with many upvotes and no linked PR |
| perf-release-pairs | optimization | merged PRs titled "x faster" or labelled performance |
| perf-regressions | optimization | closed performance-regression issues with a linked fix |
| instance-sets, research-loops, bench-parents, papers-artifacts | optimization / research | LLM scouts |

The pool started with 253 rows (237 usable) from the research pass.

- **Enrichment.** One GraphQL call per 10 GitHub repos fetches stars, SPDX licence, archived, last push, language, latest release and open PRs. Implementation rows also get their test-suite size from one tree call. A 0-100 **priority** follows from those facts. Archived repos, forks and repos GitHub doesn't know are blocked.
- **Batch picking.** The writer gets 20 unused rows, best priority first, with at most a third from one channel. The writer turns them into 10 cards, at least 5 implementation, 2 optimization and 1 research (`quota`), skipping rows that can't make a task.
- **Pool hygiene.**
  - Rows are deduplicated by URL and version.
  - Rows are blocked when their licence forbids shipping or they can't run offline.
  - Rows go stale after three offers without being used.
- **Channels** are entries in config.json, with optional `harvest` specs of kind `gh_repo_search`, `gh_issue_search`, `gh_pr_search`, `crates_search`, `npm_search`, `homebrew`, `ossfuzz` or `swesmith`. Their state is kept in data/channels.json.

## 3. Stages

| Stage | Tokens | Model / effort | Tools | Turns | Cap | What it does |
|---|---|---|---|---|---|---|
| harvest | none | | GitHub API, registries | | | new source rows per channel |
| enrich | none | | GitHub GraphQL + tree | | | facts and priority per row |
| scout | yes | haiku / low | WebSearch, WebFetch | 25 | $0.30 | up to 12 verified rows |
| write | yes | sonnet / medium | none | 6 | $1.00 | 10 cards from 20 rows |
| L0 | none | | | | | similarity to 1,392 public tasks (kill at ≥ 0.35) and to live seeds (kill at ≥ 0.6, since cards share a template) |
| probe (smoke) | none | | Docker, 4 CPU / 4 GB each, 2 at once | | | clone at the version, fetch, offline build, run the project's own suite 3 times; verdict green, amber, red or none |
| V1 | yes | haiku / medium | WebSearch, WebFetch | 30 | $0.30 | checks the facts the harvest couldn't, plus history, similarity, sealing, band and a spike plan; 11 scores |
| V2 | yes | opus / high | none | 6 | $4.00 | independent re-score of a batch's survivors on four review dimensions; ranking |
| spike | yes | sonnet / medium, in Docker, 3 CPU / 5 GB | all, network on | 150 | $6.00 ($3.00 when green at a pinned version) | builds the reference, runs the sample and the project's tests three times (green seeds skip the build and the suite) |

Measured in a probe on 2026-10-20: a writer call cost $0.04 and took 25 s, and a Haiku V1 cost $0.04-0.07 and took about 70 s.

Stage details:
- **The probe** (pipeline/probe.sh, zero tokens; the "smoke" stage) is cached per repo and version in data/smoke.json. Source rows are probed before the writer sees them, so their seeds start V1 at once; a seed without a probed row (an own idea, a scout source) is probed after L0. It runs two throwaway containers that share a work volume. The first, with network, clones the tag (then `v<tag>`, then the default branch; a single subfolder with a manifest is used when the root has none) and downloads dependencies. The second, without network, builds and runs the project's suite three times, the third on one core, with a structured report (JUnit, go test JSON, Jest/vitest/mocha JSON, meson, automake).
  - **Verdict:** green = offline build, per-test results, identical over three runs and at least 5 passing tests (1 for CTest, meson and automake, which count whole test programs); none = no build system at the root (a data, spec or test-vector repo; no penalty); red = the build failed and no test ran; amber otherwise, including builds that ran out of memory or time, or whose hinted packages failed to install. Row priority: green +25, amber +5, red -25. V1, V2 and the spike see the counts, failures, flaky tests, timings and commands as facts.
  - **Caps:** a seed's probe gets clone 5, fetch 15, build 20 and 3 x 10 minutes of tests (`smoke.caps`); a row probe only ranks the row, so it gets fetch 10, build 10 and 3 x 5 minutes (`smoke.row_caps`). Hitting a cap gives amber, not red.
  - **Hints:** when a repo has recipe hints (data/hints.json), the probe installs those apt packages in the fetch phase, keeps the `.deb` files in the work volume and installs them offline in the build phase. Names Debian doesn't know are skipped.
  - **Kills and retries:** a repo that can't be cloned, and that the GitHub API reports as gone, is killed (K2). Only one probe of a repo and version runs at a time, and never while a spike uses that build tree. A row whose probe failed three times is written without probe facts; at the next run start it is probed again. An infrastructure error (Docker, network, missing image, a reachable repo that fails to clone, a timeout) is retried instead. Amber and red aren't fatal.
  - **Spike reuse:** a row probe keeps only its facts. When a seed with a green or amber probe reaches the spike, it is probed again and that build tree (Docker volume `cgp-work-*`) is mounted at /p in its spike. The spike also mounts the probe's download and build caches, so a reused tree builds offline. A green spike whose probe built the pinned version reuses the tree and skips the suite step, at $3 and a 60-minute limit; when the probe built the default branch (rows with prose versions), the spike checks out the pinned version first and runs with the normal caps. A probe that hit its caps isn't repeated before the spike. Every 10 minutes the runner removes volumes no `v2-pass` seed needs. Download and build caches live in shared volumes (`cg-cargo`, `cg-gomod`, `cg-pip`, `cg-npm`, `cg-ccache` and others).
  - In a test on 32 repos, 63 % ended green, in a median of about 62 s.
- **V1** gets the GitHub facts and the probe result up front, so its tool calls go to what's left. The runner then requests every URL V1 cited, in parallel, as a browser would; only a 404 or 410 answer or a domain that doesn't resolve counts as dead (bot walls, timeouts and server errors don't). If more than half are dead, Real is capped at 2 (a K2 kill); if more than a third are dead, or a fact V1 marked confirmed cites a dead URL (a guessed path or branch name, often), at 3. E1 evidence needs a live `evidence_url`, otherwise it counts as E0.
- **V2** sees each card with V1's evidence (facts, URLs, lookup verdict, spike plan, dead links) but never V1's scores, which would anchor it. A seed the judge leaves out goes to the next judge call; one it leaves out twice is parked at `v1-pass`.
- **The spike** aims for 60 minutes (the hard limit is 90). It builds the reference and runs about 10 cases first, and stops early if that fails. It reads the repo's CI config to learn its build and test commands, confirms the build and one grading run work offline, and leaves SPIKE.md with its commands and results; an inconclusive spike gets one more attempt that continues from SPIKE.md. For `feature` ideas, which have no reference yet, it checks instead that the repo builds offline, that its tests are deterministic, and that nothing upstream implements the feature.
- **Spike verdicts** are mapped by the runner, first failure wins: reference not built K5, no oracle K3, not deterministic K4, no headroom K8, the untouched start doesn't score 0 K3, grading needs the network K7, a reference under 150 changed lines (600 for `feature`) K10, an optimization whose faster version changes the output K5, and for implementation ideas no sampled cases K3 or under 95 % of cases passed K5 (optimization and research ideas are judged on the measured speedup or metric gap instead). `feature` ideas have no reference yet, so the oracle and case checks wait for the bundle build. Otherwise a `fail` takes the spike's own kill code (K5 if none); grading that depends on a feature gVisor lacks is K7.
- **Prompts** live in pipeline/prompts.txt. Each stage's system prompt is the COMMON section plus that stage's section, written once to ~/.cache/cgpipe/ and served from the prompt cache. Only the stage's input goes in the message.

## 4. Cards, methods and scoring

**The writer's card** has these fields:
- **title**
- **source:** URL @ version, plus the licence
- **task:** what /app ships, what the agent builds or speeds up, and the interface
- **grading:** the oracle, the hidden-set generator and the tolerance
- **reference:** where it comes from, and why it scores 1 or the speedup it gets
- **band:** the budget tier (2, 4, 8 or 20 h), and why a frontier agent finishes the scope in some trials but not on average
- **cheat:** the obvious shortcut and how it is closed
- **family, class and method**

V1 adds a full card on top.

| Method | Class | Idea shape |
|---|---|---|
| conform | impl | implement part of a standard, graded by its conformance suite plus generated hidden cases |
| port | impl | port a real library to another language; an existing permissive port is the reference |
| diffref | impl | match a real executable on generated inputs |
| feature | impl | an original multi-part feature for a pinned commit of an active repo, ideally a long-standing upstream issue; hidden behavioural tests plus the repo's own suite |
| rebuild | impl | remove a real subsystem from a pinned project; its tests and the original grade the rebuild |
| perfseries | opt | baseline release vs a faster later release with unchanged output |
| incident | impl/opt | a real regression or bug at scale, graded on a replayed workload |
| research | research | a train-evaluate loop on open data with an OOD split |
| mutate | any | move a public task's lever onto a different real subject |
| own | any | your idea (`add-idea`), enters at V1 |

The default mix is conform 20 %, port 15 %, diffref 15 %, perfseries 15 %, feature 15 %, research 10 %, rebuild 5 % and incident 5 % (`method_mix`).

**Scores.** Each criterion is scored 1-5, with its weight in brackets:

| Criterion | Weight | Meaning |
|---|---|---|
| Real | 3 | a real source with a paper trail |
| Surf | 3 | grading-surface size |
| Ref | 2 | reference strength |
| Band | 3 | expected difficulty band |
| Hor | 2 | long horizon |
| Multi | 2 | many levers, smooth credit |
| Seal | 2 | oracle and reference out of reach |
| Nov | 2 | novelty against public tasks (not whether open-source implementations exist) |
| Lic | 1 | the licence allows shipping |
| Fit | 1 | fits the sandbox |
| Build | 1 | our build cost |

The runner computes the score as `round(100 × Σ weight·value / 110)`, from 20 to 100; it never takes a total from a model.

**Band evidence caps.** Band is capped at 3 with no evidence (E0) and at 4 with a dated public source (E1).

**Gates.** A criterion at 2 or below kills the seed, whatever its total:

| Criterion | Kill code |
|---|---|
| Real | K2 |
| Surf | K3 |
| Ref | K5 |
| Band | K8 |
| Hor or Multi | K10 |
| Seal | K11 |
| Nov | K1 |
| Lic | K6 |
| Fit | K7 |

Build at 1 also kills (K12).

**Lines.** V1 keeps a seed at 65 or more. V2 keeps it when `final = min(V1, V2)` is 70 or more. Below a line, the kill code is K8.

**Spike pass.** A spike validates the idea when its verdict is pass and none of the runner's checks fails (section 3, spike verdicts).

| Code | Kill reason |
|---|---|
| K1 | near-duplicate of a public task or another seed |
| K2 | no real source, or the repo can't be cloned |
| K3 | grading surface too small or hand-rolled |
| K4 | not deterministically gradable or too noisy |
| K5 | no strong reference obtainable |
| K6 | licence forbids shipping |
| K7 | GPU, network at run time, > 8 CPU / 16 GB, or a missing gVisor feature |
| K8 | too easy, or below the score line |
| K9 | too hard: no trial would reach 0.9 of the reference (implementation) or beat the start (optimization, research), or no partial-credit curve |
| K10 | not long-horizon, or one-lever |
| K11 | cannot be sealed |
| K12 | our build cost over 5 days |
| K13 | a V1 call failed three times (set by the runner; a spike that fails three times parks its seed instead) |

Seed ids are `S-im-NNN`, `S-op-NNN` and `S-rs-NNN`. A seed's status runs `short` → `l0-pass` → `v1-pass` → `v2-pass` → `validated`, or becomes `killed:Kn` at any stage.
