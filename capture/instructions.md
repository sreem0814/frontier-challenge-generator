# Authoring frontier tasks

This project collects the hardest tier of software-engineering evaluation tasks: problems drawn from real engineering work that a frontier coding agent works on *autonomously for 2–20 hours*, graded *objectively by a sealed verifier* on a calibrated 0–1 scale — no human in the loop. The bar is high and the pipeline is strict; nearly every rejection traces back to a rule on this page, so read it fully before your first submission.

## The bar — what a passing task looks like

- **A substantial system, worked like real engineering.** The agent lives in `/app` with a genuine edit → build → run → measure loop: several interacting modules, a real toolchain (cargo, zig, cabal, npm, CUDA, torch…), hundreds to thousands of lines. Difficulty comes from a large surface and deep dependency chains — profile, change, regress, repeat — never from one hard trick. Your reference solution carries the same scale: hundreds of changed or added lines.
- **Real, with a paper trail — a hard gate.** The task comes from something that exists outside your bundle: a real repository at a pinned commit, a real bug report, regression or review, a real dataset, a published standard or protocol, or an internal engineering record — and `PROVENANCE.md` says which. Renaming or scaling down a real subject is fine and often necessary to keep the task sealed. What fails: algorithm puzzles dressed up as engineering, invented worlds, formats and simulators whose rules are your choices alone, and tasks that only test domain knowledge.
- **One objective, a calibrated reward in [0, 1].** Hard gates first (build, correctness, anti-cheat — any failure scores exactly 0), then a continuous score. The untouched starting state scores **exactly 0**; your reference solution defines the ceiling (exactly 1 for implementation). Partial progress earns proportional credit.
- **Scored on behavior, on inputs the agent never saw.** Differential tests, a conformance suite, a measured speedup, a quality metric on a hidden split — never grepping source or checking that files exist. Tests must not overfit to your reference: a different but equally valid solution has to pass.
- **A sealed grader.** Everything the reward compares against — held-out cases, the reference, the reward script — lives under `tests/` or `solution/`, is mounted only at grading time, and never ships into the image.
- **Genuinely long-horizon — a hard gate.** Pick the budget tier the work really needs (8 hours is the median). During the difficulty probe at least one trial must do a substantial amount of work, measured in the output the agent generates — a short, tricky ask fails, however hard it is to get right.
- **Harder than the frontier, measured.** A frontier agent attempts the task at the full budget, several times. If it gets close to your reference solution on average and a weaker model keeps up with it, the task is too easy (see How a task reaches review below) — so the reference is the strongest solution you can build, not a passing one.
- **A complete engineering contract.** Public-grade instructions run roughly 700–3,350 words because they fully specify the system: workspace map, the delivery interface (the files to change, the binary or library to build with its symbols and signatures, the service and its port, the import path — whatever the verifier calls), the build and self-check loop, the exact scoring formula with every hard gate, the time budget, constraints, and autonomy rules. Terse voice, complete content.
- **No platform fingerprints.** Nothing in the bundle may reference this program, this platform or its clients, evaluation vocabulary (“the solver”, “held-out”, “reward hacking”), or a public benchmark — the pipeline hard-rejects blocked terms. Citing the task’s real upstream source in PROVENANCE.md is expected; that is not a platform reference.

## Core workflow

The workflow that consistently produces passing tasks anchors every task to a **real, externally-defined artifact graded by its own comprehensive surface** — a spec, a reference implementation, a real system’s behavior — rather than a hand-authored test list. Hand-rolled suites end up too small and get saturated; the real artifact is both the difficulty and a free oracle.

1. **Pick a real subject too big to fully cover.** A codebase, format, protocol or engine with a broad behavioral surface forces broad partial credit and keeps a next improvement always available. Write down where it came from as you go — that becomes PROVENANCE.md.
2. **Run a cheap feasibility spike before building anything.** Can you grade a from-scratch attempt against the reference? Is the measurement deterministic? If validation will be expensive, find out now.
3. **Build the strongest reference you can, then calibrate the reward to it.** The reference sets the ceiling the reward is normalized against and the bar the frontier probe has to fall short of.
4. **Build a differential verifier with per-case scoring** and a hidden/visible split. Fuzz inputs, run your reference, freeze the outputs — that is your hidden set. Fixed denominator: crashed or skipped cases count as failures.
5. **Structural anti-cheat.** Keep the real artifact off the agent’s PATH, seal grader and reference under tests/ and solution/, make the verifier self-contained, and harden it before scoring (see verifier hygiene).
6. **Validate locally before submitting:** the untouched state scores exactly 0, the reference reaches its ceiling with the same score on repeat runs, a deliberate cheater scores 0, and every run leaves the reward files. The bundle must run the same way locally and in the cloud — no paths, env vars or tools that only the cloud runner provides.
7. **Final package audit.** Diff the bundle for leaks, blocked terms, and anything that reads machine-written.

```
# from the task directory, with docker running:
harbor run -p . -a nop -e docker -k 1      # untouched: reward exactly 0
harbor run -p . -a oracle -e docker -k 2   # reference: its ceiling on both runs, same score
# each trial's verifier/ dir: reward.txt, reward.json, details.json, evidence.json
# nothing graded may ship into the image:
find environment -type f | sort            # no tests/, no reference, no answers
grep -rln "compute_reward\|solve.sh" environment/ && echo "LEAK — fix before submitting"
```

## The three classes

Every task belongs to exactly one class, set on the submit page and repeated as `[metadata] paradigm` in task.toml. Each class has its own deliverable and scoring shape.

### Implementation — paradigm = "implementation"

Build, port or rewrite a functionally complete artifact — a CLI, a shared library, a compiler, a protocol server — from a specification or an existing system, often across languages. Reward = the fraction of a sealed behavioral suite passed, over the cases your reference passes, so the untouched stub scores exactly 0 and the reference scores exactly 1 on every run. Hard gates: the build and anti-cheat.

### Performance — paradigm = "optimization"

Ship a correct, already-running baseline; the agent makes it faster without changing its behavior. The correctness gate is an equivalence check independent of the optimized path — weakening outputs to go faster scores 0. Measure a robust proxy: instruction counts (callgrind) or fixed operation budgets on CPU, paired or alternating timing with warmup and medians — never a single wall-clock sample.

The reward is bounded and calibrated to your reference. With *s* the measured speedup over the shipped baseline, *S* the speedup your reference measures, and *d* a small noise margin: `u = clamp((s − 1 − d) / (S − 1 − d), 0, 1)`, `reward = 2^u − 1`. At or below parity scores 0 (a regression is never rewarded), matching the reference scores 1, and there is no credit past it — unbounded speedup ratios are not accepted. You may set *S* above what your reference reaches as a stretch target, as long as the reference still scores at least 0.5.

### Research — paradigm = "research"

A real train → evaluate → iterate loop inside the budget, with no unique correct answer. The verifier scores the *actual artifact* (checkpoint, program, compressed output) on a deliberately out-of-distribution hidden split, after domain constraints and an authenticity audit of the deliverable. Normalize the raw metric between the shipped starting point and your reference: `reward = clamp((metric − baseline) / (reference − baseline), 0, 1)`, so a never-trained artifact scores 0. Checking your own bar costs a real training run — **run your reference end to end before claiming its number**. Research tasks are the rarest and most valuable class.

## Bundle layout

Submit one zip of the task directory. The pipeline hard-requires:

| task.toml | Identity, class metadata, the budget tier, and resources — see the next section. |
| --- | --- |
| instruction.md | The full contract (see the bar above). States the time budget in hours and asks the agent to schedule against it, points at /app/.timer, and states the exact reward formula and every hard gate with the self-check the agent can run for it. 250 words is the hard floor; passing tasks run far longer. |
| PROVENANCE.md | Where the task comes from and how it was built — see Provenance below. |
| environment/ | Becomes /app. The Dockerfile: a debian-family base pinned to a version tag (a digest is better), every dependency pre-installed (no network at runtime), the Claude Code CLI installed, ending as root (ENV PAGER=cat GIT_PAGER=cat is recommended). Your system, visible examples, and a convenience self-check that does not read tests/. |
| environment/timer.sh | The canonical timer daemon, copied exactly from the section below, plus the Dockerfile tail. |
| tests/ | Sealed. test.sh hardens the environment, collects evidence and runs anti-cheat into /logs/verifier/evidence.json; compute_reward.py makes every scoring decision and writes reward.txt, reward.json and details.json. Plus the hidden data, frozen baselines and reference outputs. |
| solution/solve.sh | Required for every class: the strongest reference you can build, shipped as source (not an archive), at least 150 non-blank code lines across solution/. It produces the deliverable only — it never writes /logs/verifier or touches /tests. |

Nothing else that would help an agent cheat ships in the bundle: no `cheat/` directory, and no grader or reference artifact under `environment/`.

## task.toml

The class, compute and language fields are how the collection is balanced, so they are checked exactly: `paradigm` must match the class you submit under (lowercase), `compute` must match `[environment] gpus`, and `languages` lists what the agent writes. `[task] name` is the organisation prefix given on the submit page (`<org>/`) plus exactly the name you submit under. `[agent] timeout_sec` must sit on a budget tier, and the same budget goes in `[environment.env] TASK_BUDGET_SECS` so the timer starts on any runner.

```
[task]
name = "<org>/<task-name>"        # the slug you submit under
description = "One or two sentences on what the task is."

[metadata]
paradigm = "optimization"         # implementation | optimization | research (lowercase)
compute = "cpu"                   # cpu | gpu — must match [environment] gpus
languages = ["c", "python"]       # what the agent writes
category = "parsers"
difficulty = "frontier"
tags = ["xml", "simd"]
oracle_reward_threshold = 0.9     # optional: what your reference reliably scores
# reward_cap = "capped"           # research only, required: "uncapped" if your metric can keep improving past your reference

[agent]
timeout_sec = 28800               # a budget tier: 7200 | 14400 | 28800 | 72000

[verifier]
timeout_sec = 7200

[environment]
allow_internet = false
cpus = 8
memory_mb = 32768
gpus = 0

[environment.env]
TASK_BUDGET_SECS = "28800"        # the same budget, as a string
```

Limits: `[verifier] timeout_sec` ≤ 86400, `allow_internet = false`, `cpus` ≤ 16, `memory_mb` ≤ 131072, `gpus` ≤ 1. `[environment.env]` may not set loader or shell-startup variables (`LD_*`, `PATH`, `PYTHONPATH`, `BASH_ENV`…) — they reach the verifier’s process too.

No `docker_image` — the platform builds your environment from the Dockerfile. Every value is a fixed literal: no `${VAR}` interpolation, no network-policy overrides, and no variables injected into the verifier. Never put an API key or token in task.toml: tasks run offline, so none is needed, and task.toml ships to the client. Research tasks also set `reward_cap` (see the difficulty probe below); GPU tasks set `gpu_types = ["H100"]` (see GPU tasks).

## Provenance

Every bundle carries `PROVENANCE.md` at its root — at least 80 words — written for a reviewer who will check it against the bundle:

- **The source.** The repository URL and the exact commit or release; the bug report, regression or review it came from; the dataset and its version; the published standard; or the internal engineering record it was distilled from.
- **The extraction.** What the environment ships and what you removed, renamed or scaled down; how the reference solution was produced; how the tests and the hidden set were derived (frozen reference outputs, real traces, an upstream conformance suite).
- **Why it is real work.** What a practitioner would be doing when they hit this problem.

The quality check reads PROVENANCE.md beside the environment: a source that does not match what the bundle contains fails grounding, and so does a task with no real source at all, however polished.

## Timer daemon (required)

Agents pace themselves badly on long-horizon work: the container’s system clock tells them nothing about the real budget, and without a trustworthy signal they assume time is short and give up hours early. Every task therefore ships a timer daemon that the harness arms at trial start, exposing the true remaining budget as files the agent can poll. Your instruction.md must point the agent at it (the structure check rejects bundles that don’t).

environment/timer.sh — copy exactly (the runtime depends on this contract):

```
#!/usr/bin/env bash
# Background task timer daemon. Writes /app/.timer/* so the agent can pace itself.
set -u

TIMER_DIR="/app/.timer"
PID_FILE="$TIMER_DIR/timer.pid"
mkdir -p "$TIMER_DIR"

if [ -f "$PID_FILE" ]; then
    EXISTING_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        exit 0
    fi
fi
echo $$ > "$PID_FILE"

# The platform injects TASK_BUDGET_SECS when it arms the timer in the task
# sandbox. Without it (e.g. inside an image BUILD container), refuse to start:
# a defaulted budget once held image builds hostage for its full duration.
if [ -z "${TASK_BUDGET_SECS:-}" ]; then
    echo "[TIMER] TASK_BUDGET_SECS not set — not starting" >&2
    rm -f "$PID_FILE"
    exit 0
fi

START_EPOCH=$(date +%s)
BUDGET_SECS="$TASK_BUDGET_SECS"
echo "$START_EPOCH" > "$TIMER_DIR/start_epoch"
echo "$BUDGET_SECS" > "$TIMER_DIR/budget_secs"

while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START_EPOCH))
    REMAINING=$((BUDGET_SECS - ELAPSED))
    [ "$REMAINING" -lt 0 ] && REMAINING=0
    echo "$REMAINING" > "$TIMER_DIR/remaining_secs"
    echo "$ELAPSED" > "$TIMER_DIR/elapsed_secs"

    if [ "$REMAINING" -le 1800 ] && [ ! -f "$TIMER_DIR/alert_30min" ]; then
        touch "$TIMER_DIR/alert_30min"; echo "[TIMER] 30 minutes remaining" >&2
    fi
    if [ "$REMAINING" -le 600 ] && [ ! -f "$TIMER_DIR/alert_10min" ]; then
        touch "$TIMER_DIR/alert_10min"; echo "[TIMER] 10 minutes remaining" >&2
    fi
    if [ "$REMAINING" -le 300 ] && [ ! -f "$TIMER_DIR/alert_5min" ]; then
        touch "$TIMER_DIR/alert_5min"; echo "[TIMER] 5 minutes remaining" >&2
    fi
    [ "$REMAINING" -le 0 ] && { echo "[TIMER] Time expired" >&2; break; }
    sleep 10
done
```

Dockerfile tail — append verbatim:

```
# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
```

The platform starts the timer for you in the task sandbox. For local validation runs, start it yourself: `TASK_BUDGET_SECS=3600 /app/timer.sh &`. Never wire it into `BASH_ENV` or an image entrypoint — the structure check rejects that.

In instruction.md, state the budget in hours and reference the timer the way a real hand-off note would — e.g. `cat /app/.timer/remaining_secs` before long steps; `alert_30min` / `alert_10min` appear as the budget winds down.

## Autonomy guidance — write your own voice

Every instruction ends with operating rules for autonomous work. The recurring ideas: never stop to ask; check remaining time before big moves; keep a valid build/submission at all times; pursue the highest-payoff next improvement and revert what doesn’t measurably help; optimize for the hidden set, not the visible sample; partial credit always scores. Two examples below — **do not paste either**; identical wording across tasks reads as templated and the quality check flags it. Express the ideas that fit your task, in your task’s voice.

```
## Operating rules

Work autonomously until interrupted — never stop to ask a question. Check
`cat /app/.timer/remaining_secs` before any long build or benchmark run and
leave at least 20 minutes for a final validation pass. Keep the build green at
all times: grading is continuous, so a working partial implementation always
scores and a broken tree scores nothing. Chase the highest-payoff gap next,
and revert any change that doesn't measurably help. The hidden set is much
larger than the visible samples — optimize for generalization, not for the
examples you can see.
```

```
## How to run this

You have full autonomy; no one will answer questions. Pace yourself against
/app/.timer (alert_30min / alert_10min appear as the budget winds down — the
system clock is NOT a reliable guide to your remaining budget). Partial
credit is real: every conformance case you pass counts, so never leave the
tree in a state that fails to build. When a direction stalls, bank the win,
revert the experiment, and take the next-most-valuable case. There is always
a real next improvement — the surface is deeper than it looks.
```

## Reward contract

Scoring happens in two stages. `tests/test.sh` collects evidence and runs anti-cheat — build result, run status, anti-cheat results — into `/logs/verifier/evidence.json`, on every path: a failed build is evidence too. `tests/compute_reward.py` makes every scoring decision from that evidence and writes three files, also on every path:

| reward.txt | One float in [0, 1]. |
| --- | --- |
| reward.json | Flat, numbers only: "reward" and "score" (the same value as reward.txt), "valid" (1, or 0 for an infrastructure fault), plus any numeric components. Nested objects or strings here break the evaluation harness. |
| details.json | "subscores" (one entry per component — including the continuous score behind every hard gate) and "additional_data": {"reason": "…"} saying why the run scored what it did. |

1. **Bounded and calibrated:** the untouched state scores exactly 0; the reference reaches the ceiling (exactly 1 for implementation, at least 0.5 otherwise — declare what it reliably scores as `[metadata] oracle_reward_threshold`).
2. **Hard gates → 0:** build failure, correctness failure and cheat detection score exactly 0 — a crash can never raise a score. Every hard gate has a self-check the agent can run and a continuous subscore approaching it, never a silent cliff.
3. **valid means the run was measurable:** write `valid = 0` only when the harness failed (no GPU visible, a runtime that would not start) — never for a wrong answer, and never for the untouched starting state, which is measurable and scores 0. A valid=0 run scores 0 and is retried, not graded.
4. **Fixed denominator:** the hidden set is fixed; erroring or skipping cases counts as failing them.
5. **Continuous and monotone:** more real progress always means more reward.
6. **Deterministic:** the same state gets the same score — repeated reference runs must agree within 0.05.
7. **Exit codes follow the score:** test.sh exits non-zero when a gate fails (the untouched state) and zero on a scoring run (the reference).

```
# tests/compute_reward.py — every scoring decision, then the three files.
import json
from pathlib import Path

OUT = Path("/logs/verifier")
ev = json.loads((OUT / "evidence.json").read_text())

def emit(reward, valid, reason, subscores):
    reward = round(min(1.0, max(0.0, reward)), 6)
    flat = {"reward": reward, "score": reward, "valid": int(valid)}
    flat.update({k: round(v, 6) for k, v in subscores.items()})   # numbers only
    (OUT / "reward.json").write_text(json.dumps(flat))
    (OUT / "reward.txt").write_text(f"{reward}\n")
    (OUT / "details.json").write_text(json.dumps({
        "subscores": [{"name": k, "score": v} for k, v in subscores.items()],
        "additional_data": {"reason": reason},
    }))
    raise SystemExit(0 if reward > 0 else 1)

if not ev["runtime_ok"]:                     # the harness failed, not the agent
    emit(0.0, 0, "runtime unavailable: " + ev["runtime_error"], {})
if ev["cheat_detected"] or not ev["build_ok"]:   # hard gates first
    emit(0.0, 1, ev["gate_reason"], {"correctness": 0.0})
correctness = ev["cases_passed"] / ev["cases_total"]    # fixed denominator
if correctness < 1.0:
    emit(0.0, 1, "outputs differ from the baseline", {"correctness": correctness})

# Optimization: bounded, calibrated to the speedup the reference measured.
s, s_ref, d = ev["speedup"], 6.4, 0.02       # d: the measurement's noise margin
u = min(1.0, max(0.0, (s - 1 - d) / (s_ref - 1 - d)))
emit(2 ** u - 1, 1, f"speedup {s:.2f}x", {"correctness": 1.0, "speedup": s})
```

## Verifier hygiene

The verifier runs in the same container the agent just had root in, beside the evaluation harness. Write it so that neither can corrupt the other:

- **Harden before scoring:** reset `PATH`, unset loader and interpreter variables, run Python with `-E -s`, and never import from /app into the scoring process.
- **Stop processes by PID — or parent, process group, pidfile, or an unprivileged user — never by name:** `pkill -f python`, `killall` and `kill -1` also kill the harness. Nothing the verifier started may still be running when the reward is written. Every script under `tests/` is read as the verifier’s own unless it sits in a data directory (`cases/`, `fixtures/`, `data/`, `expected/` …) and the verifier only feeds it to the candidate.
- **No loader hooks in the image environment:** `LD_PRELOAD`, `LD_AUDIT`, `BASH_ENV`, `SHELLOPTS`, `BASHOPTS`, `GCONV_PATH`, `PROMPT_COMMAND`, or an `LD_LIBRARY_PATH` entry under /app, /tmp, /var/tmp, /home, /root, /workspace or a relative path act on the verifier’s shell before test.sh can scrub them. Set them only in the commands that need them.
- **No oracle-mode branches:** anything the environment can set, the agent can set — the reference passes the same checks as any candidate.
- **No reward literals in shell:** every non-zero reward comes from compute_reward.py scoring the evidence.
- **End the image as root.** Harnesses stage /solution, /tests and /logs as the image’s default user. To run the agent unprivileged — the stronger isolation — create the user in the image and set `[agent] user` in task.toml.

```
#!/usr/bin/env bash
# tests/test.sh — evidence and anti-cheat only; compute_reward.py decides the score.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH BASH_ENV
mkdir -p /logs/verifier

/app/build/candidate --serve 9000 & CANDIDATE=$!     # whatever the deliverable is
python3 -E -s /tests/collect.py --port 9000 \
  > /logs/verifier/evidence.json                     # build, run status, anti-cheat
kill "$CANDIDATE" 2>/dev/null; wait "$CANDIDATE" 2>/dev/null   # by PID, never by name

exec python3 -E -s /tests/compute_reward.py          # its exit code is the run's
```

## Sandbox limits

Every run executes in a cloud sandbox under gVisor, which implements its own Linux kernel. A few kernel features your verifier may reach for are missing there, so a verifier built on them cannot measure anything: every run reports `valid = 0`, the task cannot pass oracle/nop, and a rerun fails the same way. Passing under local Docker does not show it will work here. The structure check warns when a bundle uses one:

- **Landlock** is not available: its calls fail with “Function not implemented”.
- **seccomp filters whose default action kills the process** (`SCMP_ACT_KILL_PROCESS` / `SECCOMP_RET_KILL_PROCESS`): libseccomp refuses them with “Invalid argument”, so the filter is never installed.
- **valgrind** crashes (SIGSEGV) on most runs, even on `/bin/true` — instruction counts from it are not a usable measurement here.
- **Execute-only files** (`chmod 0711`, `0111` and the like): unlike Linux, the sandbox needs read permission to execute a file, so a binary that another user runs without read access fails with “Permission denied”. Make an executable that another user runs readable (`chmod 0755`); a `0711` directory is fine.
- **Limiting or removing POSIX message queues** (`RLIMIT_MSGQUEUE`, `ulimit -q`, `mq_unlink`) is not supported: setting the limit fails, and in a `preexec_fn` the child never starts. Don’t set `RLIMIT_MSGQUEUE` or remove queues, or fall back when the call fails.

Isolate the code you grade with what does work — a separate unprivileged user, file permissions, process groups and resource limits — or make your extra isolation fall back when the feature is unavailable instead of declaring every run unmeasurable. Measure performance with repeated wall-clock timing and report the median.

## GPU tasks

- Set `gpus = 1`, `gpu_types = ["H100"]` — GPU tasks run on H100, and any other class fails structure — and `compute = "gpu"`.
- Pin a CUDA build of torch (`torch==X.Y.Z+cuNNN` from the matching `download.pytorch.org/whl/cuNNN` index). An unpinned install can land a CPU wheel and every GPU path silently falls back.
- The verifier checks for the GPU first (`torch.cuda.is_available()` or `nvidia-smi`). No GPU means `valid = 0` — never score a CPU fallback as if it were the GPU result.
- Time GPU work with warmup, synchronization and repeated runs; report the median.
- Declare the hardware in task.toml and nowhere else. The startup scripts and verifier must also run on a local machine (`harbor run -e docker` with a GPU): detect the GPU at runtime instead of assuming a specific model, and never depend on anything only the cloud runner provides.

## What the pipeline checks

Every submission runs the full pipeline before human review, and you watch each stage live on your task page — including agent trajectories as they stream in.

1. **Structure** — required files, task.toml policy and metadata, the timer, provenance, the reward-file contract, verifier hygiene, image hygiene, GPU rules and blocked terms. Instant feedback at submit.
2. **Similarity** — the task is compared against every task in the corpus, yours included. Too close to an existing task is rejected; you see the verdict, not the scores.
3. **Task quality check** — an agentic reviewer reads the whole bundle against the quality rubric, before anything runs: grounded in the real source PROVENANCE.md names, a fully specified deliverable, a calibrated bounded reward with two-stage scoring, behavioral scoring on unseen inputs, a verifier the agent cannot reach, a hard GPU gate, and a local way for the agent to estimate its score. It also checks that the task is **fair**: nothing instruction.md tells the agent may be contradicted by what your grader actually scores or enforces — a different path or interface, a different metric, a cap on a reward the instruction says keeps rising, a gate on something the instruction allows, or a tighter limit than the one you published. Keeping scoring internals (weights, tolerances, hidden cases) out of the instruction is fine; promising something the grader does not do is not. Blocking criteria reject the task; advisory ones go to the reviewer. It runs first so you can fix the instruction before the paid stages.
4. **Oracle & nop** — the untouched state and your reference run on the real harness (twice each on CPU). The untouched state must score exactly 0 on every run; the reference must reach its ceiling on every run, repeats must agree, and every run must leave the reward files in the contract shape.
5. **Adversarial probe** — a frontier agent is told to maximize the score without doing the work. If it earns credit by getting around the task — reading hidden data, patching the harness, faking the deliverable — the task fails.
6. **Second-model check** — a second, weaker model (Qwen) runs eight trials on your task before the difficulty probe. If it already does too well for any capability gap to be left (see the review gate below), the task fails as too easy here and the difficulty probe is not run.
7. **Difficulty probe** — five independent frontier-agent trials at the full budget. Each trial is scored on how far it gets from the do-nothing floor (0) to your reference (1). The task fails as too hard when the trials average below 0.05, or when no trial passes: for implementation a pass reaches your reference (a score of 0.9); for performance and research it improves on the untouched starting state. The frontier should not find your task easy: a task it finishes with little sustained work is flagged for the reviewer and may be rejected as not long-horizon, and a task it solves easily must pass the review gate below. Research tasks must declare `reward_cap` in task.toml [metadata]: `"uncapped"` when the metric can keep improving past your reference, otherwise `"capped"`. Harder tasks are still more valuable, so aim for a reference the frontier does not reach. A trial that crashes, runs on the wrong model or that your verifier marks invalid is not evidence: the stage stops as an infra failure, never as a verdict on the task.
8. **Trajectory review** — a reviewer model reads every probe trajectory. Reward hacking fails the task outright; an unfair spec, a broken environment, or difficulty that comes from something other than the engineering fails it when it shows up in more than one trial.
9. **Review gate** — the task must be in the difficulty band or show a capability gap against the second model; see the next section.
10. **Human review** — a reviewer makes the final call. Rejections always include a written reason.

Failures are classified: *verdict* failures are about the task; *infra* failures are platform faults, never the task’s verdict, and they never use up a task name’s attempts. A failure the task causes is a verdict even when it stops a run: a Dockerfile step that fails, a reference solution that exits with an error while the untouched environment runs normally, or a verifier that cannot measure because of a sandbox limit the structure check warned about or its own broken setup. A run you or an admin stop is neither, and does not use up attempts either.

## How a task reaches review

Scores here are normalized: 0 is the untouched starting state, 1 is your reference solution, and a run that beats your reference still scores 1. A task reaches human review if it meets **either** condition:

1. **In the difficulty band.** The strong model’s mean score across its difficulty-probe runs is between 0.05 and 0.85. Below 0.05 the task already fails at the difficulty probe as too hard.
2. **A capability gap against the second model.** The second, weaker model (Qwen) runs the same task, and:
  - *Implementation:* the second model solves it (reaches 0.9) in at most half its scored runs (runs left out for errors don’t count), the strong model solves it at least once, and the strong model’s solve rate is at least 20 percentage points higher.
  - *Performance and research:* the strong model makes progress (improves on the starting state) at least once, and its mean score is at least 0.20 higher than the second model’s.

**What fails:** a task above the band with no gap is rejected as too easy. The second-model check runs first, so a task on which the second model already does too well for any gap to be left is rejected as too easy before the difficulty probe, even one the strong model might have placed in the band. The usual cause is a reference solution that both models match or beat — scores are capped at your reference, so both bunch up near 1. To avoid it:

- Make your reference solution near the best result achievable, not just a good one.
- Require several strategies working together to score well.
- Avoid one-lever tasks, where a single change earns most of the score.

**Timing:** the second-model check can take many hours, and the difficulty probe starts once it finishes. Implementation tasks: the second model “does too well” when it solves more than half its scored runs. Performance and research tasks: when its mean score is so high that even a perfect strong-model score could not lead it by 0.20. A task only waiting on the second-model check doesn’t count toward your concurrent-validation limit.

**Time limits:** the second model gets more time than your task’s agent timeout. A second-model run that reaches the time limit without solving the task counts as a run it did not solve; one that solved it first counts as a solve.

**Platform failures:** errors on the second model’s side never count against you, and neither does a run that hit the time limit because the platform stalled it. Failed runs are rerun automatically; if they keep failing, the task waits for staff to look into it. A task is never failed for a missing second-model result.

## Submission limits

A submission that reaches evaluation costs hours of frontier-model time, so the platform meters it:

- A daily cap on submissions that reach evaluation — the free structure and similarity checks don’t count.
- A cap on evaluation attempts per task name. A design that keeps failing needs a new design, not another attempt.
- A short wait between submissions.
- A limit on how many of your tasks can be validating at once. A task that is only waiting on the second-model check doesn’t count toward it.
- A lower daily cap while you have a run of tasks that failed on their own issues and none has reached review yet. It lifts as soon as one of your tasks reaches review. Platform failures and runs you stop never count toward it.
- A bundle that failed the quality check, the adversarial probe, the difficulty probe or trajectory review, that sits in review, or that was rejected must change before it is resubmitted. A bundle identical to another contributor’s is refused outright.

