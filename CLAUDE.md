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
- Keep the root minimal: README.md, CLAUDE.md, capture/, pipeline/, data/, kit/, archive/.
- No new markdown files. Results go into data files (data/seeds/, data/sources.tsv); findings and decisions go into an existing section of README.md.
- kit/ is the task-building kit (kit/BUILD.md): validated ideas become bundles in kit/tasks/<task>/. archive/ holds the raw research tables (archive/research/).
