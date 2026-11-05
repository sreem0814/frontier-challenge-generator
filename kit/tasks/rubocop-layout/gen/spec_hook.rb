# frozen_string_literal: true

# gen/spec_hook.rb: loaded with `rspec -r` while the upstream Layout specs run on the full v1.92.0 tree.
# Records every (cop, configuration, source) the specs investigate, one JSON line each, to $SPEC_CASES_OUT.
# Only the inputs are kept; expected results are produced later by layout_probe.rb on the same tree.
require 'json'

module SpecCaseRecorder
  SAFE_OPTS = %i[autocorrect debug raise_error].freeze
  def _investigate(cop, processed_source)
    begin
      opts = cop.instance_variable_get(:@options) || {}
      cfg = configuration.to_h
      rec = {
        'example' => RSpec.current_example&.id,
        'cop' => cop.class.cop_name,
        'config' => cfg,
        'source' => processed_source.raw_source,
        'path' => processed_source.path && File.basename(processed_source.path),
        'ruby' => processed_source.ruby_version,
        'engine' => processed_source.parser_engine.to_s,
        'extra_options' => (opts.keys - SAFE_OPTS).map(&:to_s)
      }
      line = JSON.generate(rec)
      rec['json_safe'] = JSON.parse(line)['config'] == cfg
      $spec_case_out ||= File.open(ENV.fetch('SPEC_CASES_OUT'), 'a')
      $spec_case_out.puts(JSON.generate(rec))
    rescue StandardError => e
      warn "recorder: #{e.class}: #{e.message}"
    end
    super
  end
end
CopHelper.prepend(SpecCaseRecorder)
