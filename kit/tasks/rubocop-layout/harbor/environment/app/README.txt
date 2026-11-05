/app workspace
  rubocop/        RuboCop 1.92.0 (MIT) with the Layout department taken out. Each of the 100 files in
                  lib/rubocop/cop/layout/ keeps its documentation and an empty class; these support files
                  were deleted: lib/rubocop/cop/mixin/{check_line_breakable, empty_lines_around_body,
                  end_keyword_alignment, first_element_line_break, hash_alignment_styles,
                  multiline_element_indentation, multiline_element_line_breaks, multiline_expression_indentation,
                  multiline_literal_brace_layout, preceding_following_alignment, space_after_punctuation,
                  space_before_punctuation}.rb and lib/rubocop/cop/correctors/{space_corrector,
                  multiline_literal_brace_corrector}.rb (their autoload lines remain). spec/rubocop/cop/layout/
                  was removed. docs/modules/ROOT/pages/cops_layout.adoc and config/default.yml describe every cop
                  and option. All gems of Gemfile.lock are installed; there is no network.
  samples/        cases.jsonl.gz: sample cases with the expected offenses and corrected source.
  tools/          layout_probe.rb (the driver the grader uses) and selfcheck.py (scores your tree on the samples).
  .timer/         remaining_secs, elapsed_secs, alert_* files for the time budget.
