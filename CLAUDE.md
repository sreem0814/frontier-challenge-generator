# CLAUDE.md (CG)

Rules for Claude Code sessions in this folder. The manual is README.md. Read it before changing the pipeline.

## Source of truth
- When the user says "requirements" (or "the requirements"), they mean capture/instructions.md.
- capture/instructions.md is the single source of truth for CG. It is read-only on disk (mode 444) and changes only when the user asks; after a change, review pipeline/prompts.txt COMMON and re-pin `spec_sha256`. When anything else disagrees with it, the spec wins.
- pipeline/prompts.txt COMMON is a digest of the spec. pipeline/config.json `spec_sha256` pins the spec version the digest was written against; `cgpipe.py run` refuses to start if they differ.

## Hard rules
- Privacy: CG is private. Never contact, fetch, search for or name the task platform that receives submissions, in any file, query, prompt or commit. Its identifiers (the task-name prefix, blocked names) live only in ~/.config/cgpipe/ (`org`, `denylist.txt`), outside the repo. No personal, commercial or account details go into the project.
- Don't start the pipeline (`cgpipe.py run` without `--dry-run`) unless the user asks for it in this session.
- No outward actions: no posting, issues, PRs or submitting. The user submits.
- No API keys or tokens in any file in this folder. The spike token lives in ~/.config/cgpipe/env; CG's trial keys live on each runner in ~/cg.env (Claude keys only; each project has its own file, e.g. tb-ws's ~/tb.env). The token pool (pipeline/tokens.py) keeps named tokens in ~/.config/cgpipe/tokens.json and installs them in those two places; never print a token value or put one on a command line.
- Nothing from /work/tb-ws's confidential files (guidelines, course tips, review lessons, acceptance spec, WORKFLOW.md, task fields) is copied here. Its scripts and methods may be reused.
- Sealed grading: hidden cases, reference outputs and grader code never go into a web search, a fetched URL or a model trial's prompt.
- Downloaded code is read before it runs, and runs only with `python3 -I` or in a throwaway container.
- Licences must allow shipping an input in a task bundle. No LLM-as-a-judge verifiers.

## Files
- Keep the root minimal: README.md, CLAUDE.md, .gitignore, .gitattributes, capture/, pipeline/, data/, kit/, archive/.
- .gitattributes stores every file byte for byte (`* -text`); runtime files, data-dry/ and kit build output are git-ignored.
- No new markdown files. Results go into data files (data/seeds/, data/sources.tsv); findings and decisions go into an existing section of README.md.
- kit/ is the task-building kit (kit/BUILD.md): validated ideas become bundles in kit/tasks/<task>/. archive/ holds the raw research tables (archive/research/).

## Machines
- VM1 (this machine): research, the pipeline, probes and spikes. 8 CPUs, 22 GB, no GPU.
- Trial runners `vm2` and `vm3` (generic names shared across projects; Windows PCs with WSL 2 on Tailscale, fast internet): the bundle kit's trial runners (`CG_RUNNER_HOST=vm2|vm3`, default vm2). Setup and disk care: README section 10. Never start a run on a runner that reports DISK_LOW (~/.runner/DISK_LOW).
- VM1, VM2 and VM3 are three different PCs. VM3 is the PC tb-ws calls `tb-runner3` (same IP; tb-ws keeps that alias, CG uses `vm3`); it is shared, so tb-ws runs live there in ~/tb-runs beside CG's ~/cg-runs. VM2 is a new PC (not tb-ws's old `tb-runner`).

## Working style
- When the user says "check the dashboard" (or similar), run `python3 -I pipeline/cgpipe.py watch --once`, read its issues, bottleneck and the end of data/pipeline.log, then propose or apply the fix the issue suggests.
- Before changing cgpipe.py, run `python3 -I pipeline/cgpipe.py selftest` (zero tokens) and run it again after; all scenarios must pass.
- Subagent tiers in .claude/agents/: collector (haiku), analyst (sonnet), judge (opus); each returns 10 lines or fewer plus file paths.
- Keep facts, inferences (marked INFERRED) and recommendations apart. Record versions and access dates.
- Commits are local only, made when the user asks: a single-line message, no body and no Co-Authored-By or other attribution trailer.
