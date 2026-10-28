# CG

CG produces long-horizon software-engineering tasks for frontier coding agents. Its single source of truth is [capture/instructions.md](capture/instructions.md): the task format, the bar every task must meet, and how submissions are judged. That file is read-only on disk, and wherever another file disagrees with it, the spec wins.

This README is the manual for CG's idea pipeline, `cgpipe`, which finds task ideas and validates them in parallel.

## Quick start

```
# once (section 5): build the image, then save the spike token
docker build -t cgpipe-spike:1 -f pipeline/spike.Dockerfile pipeline
bash pipeline/setup-token.sh

bash pipeline/dashboard.sh start              # web dashboard: http://127.0.0.1:8765/
python3 -I pipeline/cgpipe.py warmup          # zero tokens, 1-2 h, ends by itself; Ctrl-C is safe once about 20 rows are probed
python3 -I pipeline/cgpipe.py run --max-batches 1 --target 2 --budget 25    # pilot: 1 batch, stop at 2 validated or $25
python3 -I pipeline/cgpipe.py run             # full run: config defaults (10 validated, $150 across runs, 12 batches)

python3 -I pipeline/cgpipe.py status          # any time: sources, seeds, yields, plan usage, cost
python3 -I pipeline/cgpipe.py selftest        # after changing the code: zero-token robustness test
```

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

## 5. Setup and running

**Setup (once):**
1. **Claude Code is logged in:** `~/.local/bin/claude --version` (2.1.304 tested).
2. **The GitHub CLI is logged in:** `gh auth status`. Harvest and enrich use it: 5,000 API calls an hour and 30 searches a minute, no tokens.
3. **Image for probes and spikes:** `docker build -t cgpipe-spike:1 -f pipeline/spike.Dockerfile pipeline`. It's about 2.8 GB, with ccache and cargo-nextest for the probe, and the build checks that `claude --version` works inside it.
4. **A token for spike containers**, in your own terminal on VM1 (not through a `!` command in a Claude session):
   ```
   bash pipeline/setup-token.sh
   ```
   It runs `claude setup-token` (open the link it shows and approve), asks you to paste the token at a hidden prompt, saves it to `~/.config/cgpipe/env` with mode 600, and checks it inside the spike container with a one-word reply (under a cent). The pasted token is not echoed, not kept in shell history and not stored in this folder (`claude setup-token` itself prints it once so you can copy it). `--force` replaces an existing token. Inside a spike container the token is visible to the build scripts of the repo being built (upstream code, run as root with network): if that worries you, use a token from a separate account with its own limits.

**Token pool (several accounts).** With more than one Claude account, keep their OAuth tokens in a pool and let CG spread the work: `python3 -I pipeline/tokens.py add <name> --plan "max 5x"` asks for the token at a hidden prompt (run it in your own terminal) and stores it in `~/.config/cgpipe/tokens.json` (mode 600, outside this folder). Three roles use pool tokens: `pipeline` (spike containers and the runner's own calls on VM 1, written to `~/.config/cgpipe/env`) and `vm2`, `vm3` (each runner's `~/cg.env`, for model trials). `list` shows each token's plan, roles and both limits (session and weekly) without its value; `check` reads the limits with one tiny Haiku call per token; `use <name> --for vm2` assigns one by hand; `auto` gives each role the token with the most headroom, preferring a different token per role. `remove` and `rename` manage names, and `adopt <name> --from vm2` takes a token already installed somewhere into the pool. The watchdog re-reads the limits every 30 minutes and moves the pipeline role; `remote_run.sh` moves a runner's role before each model trial and refuses to start one when its token is at a limit (a trial that stops at once would look hard). VM 1's own login (this coordinator and its build agents) is not in the pool. Values travel only through files and stdin, never on a command line or in output.

**Running.** Run the Quick start commands inside tmux (`tmux new -s cgpipe`), so a run survives a closed terminal. The pilot costs about $2-3 up to the V2 verdict, plus up to $6 per spike.

**Commands** (`python3 -I pipeline/cgpipe.py <command>`):

| Command | What it does |
|---|---|
| `run` | the pipeline. Options: `--target N` (validated ideas to stop at; 0 means no target, so the budget or `max_batches` ends the run), `--budget USD`, `--max-batches N`, `--no-spike` (stop at `v2-pass`), `--no-smoke`, `--dry-run` (fake workers, no tokens) |
| `warmup` | zero tokens: harvest, enrich and probe source rows (up to about 60 ahead of the writer), then exit. Run it before `run` so the first batch doesn't wait for probes |
| `stop` | graceful stop: no new work; calls in flight finish |
| `status` | counts, kills, yields per channel and method, plan usage, cost by stage, the best seeds |
| `watch [--once]` | the dashboard in a terminal; `--once` prints one snapshot |
| `dashboard` | the web dashboard (normally started with `dashboard.sh`) |
| `try-prompts [ROWS] [V1S]` | real write and V1 calls on a few rows, in a scratch folder that is removed afterwards, to test the prompts (costs cents) |
| `similar "<text>"` | nearest public tasks and seeds to any idea |
| `add-idea "<text>"` | queue your own idea (enters at V1) |
| `requeue <seed> v1\|v2\|spike` | send a seed back to a stage |
| `import-sources <tsv>...` | add rows from research tables |
| `selftest` | zero-token robustness test |
| `ladder` / `ladder plan` | start the next model trial on each free runner from each bundle's stage (kit/BUILD.md step 7a): Qwen first, the frontier short probe, a full trial only in the band, the cheat trial last. The watchdog runs it every 10 minutes when `ladder.auto` is on; `plan` only prints the queue. `touch data/HOLD-vm2` holds a runner |

- **The budget** counts every call in data/cost.jsonl, across runs. A $25 pilot followed by `run --budget 150` leaves the rest of the $150 for the full run. A call starts only if the budget covers it plus the caps of the calls in flight.
- **Dry runs, prompt tries and selftests** each work in their own `data-dry/<name>/` folder and never touch data/.
- **`CGPIPE_DATA=<folder>`** points any command at another data folder (it needs catalog.csv, corpus-extra.tsv and sources.tsv), for example to test `warmup` on a copy without touching data/. Real runs still allow only one runner per machine.
- `add-idea`, `requeue` and `import-sources` are safest while the runner is stopped.

**The web dashboard** runs in the background:
```
bash pipeline/dashboard.sh start [--port 8765] [--interval 10]
bash pipeline/dashboard.sh status        # pid, URL, page age, whether the server answers, last log lines
bash pipeline/dashboard.sh restart | stop | logs
```

How it works:
- Every 10 s it rewrites data/dashboard.html, a self-contained page that reloads itself.
- Python's built-in server serves it on 127.0.0.1:8765, localhost only.
- To open it from your own computer, use VS Code's port forwarding, or `ssh -L 8765:127.0.0.1:8765 <VM1>`.
- The script tracks the dashboard by its PID file, refuses to start a second copy, and never affects the pipeline.

The page shows:
- **tasks ready for trials** against `build_target` (10), and every bundle in kit/tasks/ with its progress through seven steps (environment, verifier, reference, text, L0, L3, premortem), reference size, instruction length, L0 and L3 results, trial runs, last activity and latest note (all read from the bundle's own files);
- run state (running, paused or stopped, and why), spend, plan usage with reset times and pause thresholds;
- validated ideas, which ones are being built, and efficiency: cost per validated idea, spike pass rate, ideas written per validated;
- sources, and the funnel from written to validated, with kills by code and meaning;
- every running pipeline job, the bottleneck stage, progress and ETA, average time per stage;
- **issues**, each with what to ask Claude (including builds with no file changes for 90 minutes);
- the last log lines.

To have Claude look into something, say "check the cgpipe dashboard". Claude runs `watch --once`, reads the issues and the log, and proposes or applies a fix.

**Pilot checklist, before the full run:**
- Read the cards in data/seeds/.
- Compare data/cost.jsonl with the costs above.
- Read one V1 report and open its URLs.
- Read one data/spikes/<id>/SPIKE.md.
- Check how many V1 passes V2 keeps. If V2 kills most of them, set `models.v1` to `sonnet`.

## 6. Robustness

- **The spec stays the source of truth:** `run` refuses to start if capture/instructions.md no longer matches `spec_sha256` in config.json. Review COMMON, then update the hash.
- **State:** one runner at a time: data/.lock per data folder, and ~/.cache/cgpipe/run.lock per machine for real runs (probe and spike containers are shared). Writes are atomic, so a crash loses only the calls in flight; those seeds are scheduled again on the next start.
- **Typed results:** `--json-schema` checks every model output. A missing structured result counts as an error.
- **Plan limits:**
  - The runner recognises every documented limit message (session, weekly, Opus/Sonnet and spend limits, "Usage limit reached", server-side limiting, 429) and pauses until the window resets. The retry doesn't count as a failure.
  - It also reads 5-hour and weekly usage from every call, and pauses new calls at 90 % and 95 % respectively (`pace`).
- **Preflight:** `run` refuses to start when Claude Code, the `gh` login, Docker, the image or the spike token (mode 600) is missing, rather than turning every call into a failure. It also removes probe and spike containers left over from a crashed run.
- **Caps:** every call has `--max-turns` and `--max-budget-usd`. A call that hits its turn, budget or time cap is retried with 1.5x caps, not identically. A call that times out is logged at its cap, so the budget never undercounts.
- **Budget end:** when no new call fits the budget and nothing has run for a minute, the run ends as "budget reached" instead of idling.
- **Outages:** when four different model calls fail within 10 minutes with errors that look like infrastructure (a login, network, provider or Docker outage; cap hits and bad answers don't count), the runner pauses new calls for 10 minutes and doesn't count those failures; after three such pauses with no success in between, failures count again.
- **Retries:** a failed call is retried after 2 and then 4 minutes. A third failure takes the stage's fallback, so nothing loops forever:

  | Stage | Fallback after a third failure |
  |---|---|
  | V1 | the seed is killed (K13) |
  | spike | the seed is parked at `v2-pass` (it passed the judge; the failure is likely infrastructure): `requeue <id> spike` retries. A rejected spike token stops all spikes, with a dashboard issue, while V1 and V2 go on |
  | V2 | the batch's seeds are parked at `v1-pass` (never promoted on V1 scores); `requeue <id> v2` retries |
  | probe | V1 (or the spike) proceeds without it |
  | harvest | scouts cover the channel until its next harvest |
  | enrich | retried in 30 minutes; writing doesn't wait for it |
  | scout | the channel is disabled |
  | writer | no new batches this run |
- **Watchdog:** `bash pipeline/watchdog.sh install` adds a cron job that runs every 10 minutes. If the runner died without being asked to stop (a crash, or a run that ended "stalled"), it restarts it in the tmux session `cgpipe`, at most once every 30 minutes; a run that ended on purpose (stop requested, target or budget reached, warm-up done, nothing left to do) is left alone. It also restarts the web dashboard if that died. Log: data/watchdog.log; `bash pipeline/watchdog.sh uninstall` removes it. Zero tokens.
- **Stopping:**
  - `stop`, or a first Ctrl-C or SIGTERM, finishes the calls in flight. A second Ctrl-C kills them, including their probe and spike containers.
  - A leftover STOP file is cleared at start.
  - A run also ends by itself when the target is reached, the budget is spent, nothing can move, or 15 minutes pass idle.
- **Hallucination guards:**
  - Facts come from the GitHub API where possible.
  - V1 must cite a URL for every other fact, and the runner requests each one.
  - Probes and spikes test the claims in real containers.
  - Kill codes, classes, methods and families are schema enums, so a model can't write a code the runner ignores.
- **Selftest:** 19 checks, all zero-token, none touching data/:
  - the documented limit messages;
  - 16 dry-run scenarios with injected faults: happy path, resume, failing harvesters, failing writer, flaky V1, usage-limit pause, high-usage pacing, SIGTERM, batch cap, no target, failing probes, failing enrich, a judge that skips a seed, a spike re-probe for its build tree, an outage, failing spikes;
  - terminal and web dashboard rendering.

## 7. Tuning

| Symptom | Change |
|---|---|
| Most kills are K1 | add channels or harvest queries away from crowded families |
| V2 kills most V1 passes | V1 is too lenient: use `sonnet` for V1, or raise `lines.v1_keep` |
| Many K2 kills at the probe | look at the rows' URLs: deleted or private repos |
| Many amber or red probes | read `log` and `timeouts` in data/smoke.json; raise `smoke.caps` for timeouts; add the missing tool to the image |
| The first batch takes too long to start | lower the probe's `smoke.caps`, or run with `--no-smoke` (no probes; V1 and spikes run without build facts) |
| Spikes come back inconclusive | raise `timeouts_sec.spike`, `max_turns.spike` or `call_budget_usd.spike`; add the missing toolchain to the image |
| Frequent pacing pauses | lower `max_parallel_calls`, move more stages to Haiku, or run after the weekly reset |
| Too few research seeds | raise `quota.research` |

## 8. Files

```
README.md  CLAUDE.md
capture/instructions.md   the spec (read-only on disk; sha256 pinned in config.json)
pipeline/
  cgpipe.py          the runner (stdlib Python 3.10+)
  harvest.py         harvesters, enricher, and the probe's host side: containers, report parsing, verdict (no tokens)
  probe.sh           the probe inside its containers: clone, fetch, offline build, three test runs
  config.json        targets, budget, pools, models, caps, pacing, channels and harvest queries
  prompts.txt        COMMON + one section per stage (scout, write, v1, v2, spike)
  spike.Dockerfile   image for probes and spikes
  dashboard.sh       start, stop, restart, status, logs for the web dashboard
  setup-token.sh     creates and checks the spike token (~/.config/cgpipe/env)
  watchdog.sh        cron watchdog: restarts a crashed runner or dashboard (install | uninstall)
  vm/                trial-runner tools: specs.ps1, specs.sh, setup.sh, cleanup.sh (section 10)
data/
  sources.tsv        the source pool: one row per real artifact, with status, facts and priority
  catalog.csv        309 public Terminal-Bench tasks (similarity corpus)
  corpus-extra.tsv   1,083 tasks from other public benchmarks, including DeepSWE (similarity corpus)
  seeds/<id>.json    per seed: card, status, kill, facts, probe result (`smoke`), scores, V1 report, V2 scores, spike, history
  cost.jsonl         one line per model call (stage, key, model, seconds, list-price cost, turns, error)
  ...                runtime files: channels.json, smoke.json, hints.json, usage.json, state.json, pipeline.log, runs/,
                     spikes/<id>/, dashboard.html, dashboard.pid, dashboard.log
kit/                 the task-building kit: BUILD.md, scripts, tasks/<task>/ bundles (section 9)
archive/             raw research tables, not needed to run anything
~/.cache/cgpipe/     outside the repo: worker cwd and per-stage system-prompt files
~/.config/cgpipe/    outside the repo, private: env (spike token), org and denylist.txt (platform identifiers)
```

## 9. After validation

Each `validated` seed has its card, facts, probe result, V1 report, judge scores and spike notes in data/seeds/<id>.json and data/spikes/<id>/. To turn one into a task bundle, follow kit/BUILD.md.

