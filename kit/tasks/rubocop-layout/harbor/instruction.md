# Rebuild RuboCop's Layout department

`/app/rubocop` is RuboCop 1.92.0, the Ruby linter and formatter, with its whole Layout department taken out. The 100 Layout cops still exist as names: each file in `lib/rubocop/cop/layout/` keeps its documentation comment and an empty class, so the registry, the configuration and every other department load and run. But no Layout cop reports an offense or corrects anything, and the support code that only Layout cops used is gone. Your job is to bring the department back: every cop detecting exactly the offenses RuboCop 1.92.0 detects, at exactly the same source ranges, honouring every configuration option in `config/default.yml`, and autocorrecting to exactly the same output, alone and together with the other Layout cops.

## Workspace

- `/app/rubocop/` – the RuboCop tree (a git repository with one commit, the starting point). `lib/` is yours. All gems of `Gemfile.lock` are installed system-wide; `bundle exec rspec`, `bundle exec exe/rubocop` and `bundle exec ruby` work from this directory. There is no network.
- `/app/rubocop/lib/rubocop/cop/layout/*.rb` – the 100 cop stubs. Their comments carry the upstream documentation with `# bad` / `# good` examples for each style.
- `/app/rubocop/config/default.yml` – every Layout cop's options, supported styles and defaults. `docs/modules/ROOT/pages/cops_layout.adoc` is the same documentation as one page.
- Removed support files (their `autoload` lines in `lib/rubocop/cop/mixin.rb`, `lib/rubocop/cop/correctors.rb` and `lib/rubocop/cop/layout.rb` remain): the mixins `CheckLineBreakable`, `EmptyLinesAroundBody`, `EndKeywordAlignment`, `FirstElementLineBreak`, `HashAlignmentStyles`, `MultilineElementIndentation`, `MultilineElementLineBreaks`, `MultilineExpressionIndentation`, `MultilineLiteralBraceLayout`, `PrecedingFollowingAlignment`, `SpaceAfterPunctuation`, `SpaceBeforePunctuation`, and the correctors `SpaceCorrector` and `MultilineLiteralBraceCorrector`. Recreate them or structure the code your own way; only behaviour is graded.
- `spec/rubocop/cop/layout/` was removed. The rest of the spec suite and the spec helpers (`expect_offense`, `expect_correction`) are intact if you want to write your own specs.
- `/app/samples/cases.jsonl.gz` – 2,164 sample cases with expected results (format below).
- `/app/tools/layout_probe.rb` – the exact driver the grader runs. `/app/tools/selfcheck.py` – scores your tree on the samples.
- `/app/README.txt` – this map in short.

## What is graded

Only `/app/rubocop/lib/`. At grading time a clean tree is assembled from the starting `Gemfile`, `Gemfile.lock`, `rubocop.gemspec`, `config/` and `exe/` plus a copy of the regular files under your `lib/` (symlinks are not followed; `lib/` must stay under 64 MB). Edits anywhere else, including `config/default.yml`, have no effect. You may change any file in `lib/`, including code outside the Layout department, as long as RuboCop still loads.

Interface: each cop is the class `RuboCop::Cop::Layout::<Name>`, registered under the name `Layout/<Name>` exactly as in `config/default.yml`, a subclass of `RuboCop::Cop::Base` working through the normal `Team` / `Commissioner` / `Corrector` machinery. The grader finds cops with `RuboCop::Cop::Registry.global.find_by_cop_name`.

## How a case runs

Each case is one JSON object: `cops` (cop names), `config`, `source`, `path` (null or a file name), `ruby` (the target Ruby version, 2.2 to 3.4), `engine` (`parser_whitequark`, or `parser_prism` for 3.4) and `defaults`. `layout_probe.rb` does the following, from the tree's root directory:

1. Builds the configuration with `RuboCop::Config.new(hash, "/tmp/layout-probe/.rubocop.yml")`. If `defaults` is false, `hash` is the case's `config` as is (this is how the upstream specs configure a cop). If `defaults` is true, every `Layout/*` section of `config/default.yml` is loaded first and the case's sections are merged over them key by key.
2. Parses `source` with `RuboCop::ProcessedSource` for the given Ruby version and engine.
3. Creates the listed cops with options `{autocorrect: true, raise_error: true}` and runs them in one `RuboCop::Cop::Team` with deferred corrections. Unsafe corrections are applied too, as with `rubocop -A`.
4. Records the offenses of this first pass: for each cop, the sorted list of `[line, column, last_line, last_column]` of each offense's location (lines 1-based, columns 0-based). Disabled offenses (inline `rubocop:disable`) are left out.
5. Applies the corrections, re-parses and repeats until a pass changes nothing; the result is `corrected`. More than 50 passes counts as an autocorrection loop (an error).

An exception from a cop, a parse failure, more than 20 seconds on one case, or a crash of the driver process makes the case fail. Messages, severities and the `correctable` flag are not compared.

There are two kinds of case:

- **Cop cases** name one cop. The expected result has that cop's offense list (never empty) and the corrected source.
  - `spec`: inputs and configurations taken from the upstream Layout specs of 1.92.0.
  - `vary`: the same inputs after one to three whitespace and line-break edits that keep the program's AST unchanged.
  - `corpus`: real Ruby files (standard library, gems, RuboCop itself) after several such edits, run with a randomized configuration of the cop (styles from its `Supported...` list, flipped booleans, other widths and maximums) and `defaults: true`, target Ruby 3.3.
- **Dept cases** (`dept`) run all Layout cops that `config/default.yml` enables by default together on an edited real file, with `defaults: true`. Only the final `corrected` source is compared; interactions between cops, the order corrections land in, and conflicting corrections that wait for the next pass all matter.

Expected results come from the released RuboCop 1.92.0 cops run through the same driver.

## Scoring

Hard gate: the clean tree must load (`require "rubocop"` under bundler) and all 100 `Layout/*` cop names in `config/default.yml` must resolve in the registry. Failing the gate scores 0.

Each cop case earns 0.5 when that cop's offense list equals the expected list exactly, plus another 0.5 when the corrected source is also byte-identical (correction credit needs the offenses right). Each dept case earns 1 when the final source is byte-identical.

    reward = 0.9 * (sum of cop-case points) / (number of cop cases)
           + 0.1 * (dept cases passed) / (number of dept cases)

Every case counts equally, so cops with more cases weigh more; the sample file shows the mix. The graded set is fixed and separate from the samples: 14,908 cases (2,227 spec, 5,597 vary, 6,632 corpus, 452 dept) over all 100 cops, from other spec examples and other real files. Failing, erroring or timed-out cases score 0; the denominators never change. The untouched tree scores exactly 0 and the released cops score 1.

## Checking your work

    cd /app/rubocop && bundle exec ruby -e 'require "rubocop"'      # the gate
    python3 /app/tools/selfcheck.py                                    # all samples, estimate with the formula above
    python3 /app/tools/selfcheck.py --cop Layout/HashAlignment --show 3   # one cop, show failing cases
    python3 /app/tools/selfcheck.py --kind dept --show 1

`--show` prints the configuration, the expected and actual offense ranges and a diff of the corrected source. A full sample run takes well under a minute. The cop documentation and `config/default.yml` are the specification for behaviour the samples do not show; the graded cases cover far more configurations and code shapes than the samples, so build each cop to its documented behaviour rather than to the sample inputs.

## Time budget

You have 8 hours. The real remaining budget is in `/app/.timer/remaining_secs` (the system clock is not a guide); `cat` it before long runs. `alert_30min`, `alert_10min` and `alert_5min` appear in `/app/.timer/` as the end nears.

## Constraints

- Work as the `agent` user in `/app`. No network; everything you need is installed.
- Only `lib/` counts. Do not rely on files outside `/app/rubocop/lib` at grading time; the grader runs your code as a different unprivileged user with nothing else of `/app` available.
- Do not slow the department down pathologically: a case gets 20 seconds.

## Operating rules

Nobody will answer questions, so make reasonable calls and keep going. Keep RuboCop loading at every step: a syntax error anywhere in `lib/` sends the score to 0, while a half-finished cop only loses its own cases. Run the self-check often, commit working states, and move on from a cop when it stops paying. The big alignment and indentation cops (`LineLength`, `IndentationWidth`, `EndAlignment`, `MultilineMethodCallIndentation`, `ExtraSpacing`, `HashAlignment` and their kin) carry many cases; the department's corrections also have to cooperate in the dept cases. Check the timer before big refactors and leave time for a final full self-check.
