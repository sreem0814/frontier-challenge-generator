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
