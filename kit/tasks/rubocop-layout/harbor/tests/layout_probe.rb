# frozen_string_literal: true

# layout_probe.rb: run RuboCop cops on source snippets and report their offenses and autocorrected source.
#
#   ruby layout_probe.rb < cases.jsonl > results.jsonl     (from a rubocop tree, with bundler set up)
#
# Each input line is one case:
#   {"id": "...", "cops": ["Layout/Foo", ...], "config": {<full config hash>}, "source": "...",
#    "path": null | "name.rb", "ruby": 3.3, "engine": "parser_whitequark" | "parser_prism", "defaults": false}
# With "defaults": true, every Layout/* section of config/default.yml (read from the current directory) is
# merged under the case's own sections first, so cops that read another cop's settings see its defaults.
# Each output line is:
#   {"id": "...", "offenses": {"Layout/Foo": [[line, column, last_line, last_column], ...]},
#    "corrected": "<source after autocorrection>" | null, "iterations": n, "error": null | "..."}
#
# Offenses come from the first pass over the original source (sorted). The corrected source comes from
# repeating "investigate, apply all corrections" until a pass changes nothing, as `rubocop -A` does; more
# than MAX_PASSES passes is an error (an autocorrection loop). Any exception raised by a cop is an error.
require 'json'
require 'timeout'
require 'yaml'

MAX_PASSES = 50
CASE_SECONDS = Float(ENV.fetch('LAYOUT_PROBE_CASE_SECONDS', '20'))
WORK_DIR = '/tmp/layout-probe'

# Results go to a private copy of stdout; anything the code under test prints is discarded.
OUT = IO.new(STDOUT.fileno).dup
OUT.sync = true
STDOUT.reopen(File::NULL)
$stdout = STDOUT

require 'rubocop'

def processed(source, path, ruby, engine, config, registry)
  ps = RuboCop::ProcessedSource.new(source, ruby, path, parser_engine: engine)
  ps.config = config
  ps.registry = registry
  ps
end

def layout_defaults
  @layout_defaults ||= begin
    all = YAML.safe_load(File.read('config/default.yml'), permitted_classes: [Regexp, Symbol], aliases: true)
    all.select { |k, _| k.start_with?('Layout/') }
  end
end

def case_config(kase)
  return kase['config'] unless kase['defaults']

  hash = Marshal.load(Marshal.dump(layout_defaults))
  kase['config'].each { |k, v| hash[k] = v.is_a?(Hash) ? (hash[k] || {}).merge(v) : v }
  hash
end

def run_case(kase)
  RuboCop::Formatter::DisabledConfigFormatter.config_to_allow_offenses = {}
  RuboCop::Formatter::DisabledConfigFormatter.detected_styles = {}
  path = kase['path'] ? File.join(WORK_DIR, kase['path']) : nil
  ruby = kase['ruby'] || 3.3
  engine = (kase['engine'] || 'parser_whitequark').to_sym
  config = RuboCop::Config.new(case_config(kase), File.join(WORK_DIR, '.rubocop.yml'))
  classes = kase['cops'].map do |name|
    RuboCop::Cop::Registry.global.find_by_cop_name(name) or raise "unknown cop #{name}"
  end
  registry = RuboCop::Cop::Registry.new(classes)
  source = kase['source']
  offenses = nil
  passes = 0
  loop do
    ps = processed(source, path, ruby, engine, config, registry)
    raise 'source does not parse' unless ps.valid_syntax?

    cops = classes.map { |klass| klass.new(config, { autocorrect: true, raise_error: true }) }
    team = RuboCop::Cop::Team.new(cops, config, autocorrect: true, raise_error: true)
    team.defer_corrections = true
    report = team.investigate(ps)
    unless team.errors.empty?
      raise "cop error: #{team.errors.first.cop.class.cop_name}: #{team.errors.first.cause.class}"
    end

    if offenses.nil?
      offenses = Hash.new { |h, k| h[k] = [] }
      report.offenses.reject(&:disabled?).each do |o|
        loc = o.location
        offenses[o.cop_name] << [loc.line, loc.column, loc.last_line, loc.last_column]
      end
      offenses.each_value(&:sort!)
    end
    passes += 1
    new_source = team.updated_source_file? ? team.updated_source : nil
    break if new_source.nil? || new_source == source
    raise 'autocorrection loop' if passes >= MAX_PASSES

    source = new_source
  end
  { 'offenses' => offenses, 'corrected' => source, 'iterations' => passes, 'error' => nil }
end

STDIN.each_line do |line|
  next if line.strip.empty?

  kase = JSON.parse(line)
  result = begin
    Timeout.timeout(CASE_SECONDS) { run_case(kase) }
  rescue Exception => e # rubocop:disable Lint/RescueException
    raise if e.is_a?(Interrupt) || e.is_a?(SignalException)

    { 'offenses' => {}, 'corrected' => nil, 'iterations' => 0,
      'error' => "#{e.class}: #{e.message.to_s[0, 200]}" }
  end
  OUT.write(JSON.generate({ 'id' => kase['id'] }.merge(result)) + "\n")
end
