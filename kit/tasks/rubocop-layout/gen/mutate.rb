# frozen_string_literal: true

# gen/mutate.rb: layout-only mutations of real Ruby files.
#
#   ruby gen/mutate.rb <in.jsonl >out.jsonl
#   input lines:  {"id": "...", "source": "...", "seed": 123, "count": 8}
#   output lines: {"id": "...", "source": "<mutated>", "applied": ["sp_del", ...]}
#
# Every mutation edits whitespace, line breaks or comment spacing only, and is kept only when the
# mutated file still parses (Ruby 3.3 grammar, whitequark parser) to the same AST as the original.
require 'json'
require 'ripper'
require 'rubocop-ast'

def ast_of(src)
  ps = RuboCop::AST::ProcessedSource.new(src, 3.3, nil, parser_engine: :parser_whitequark)
  return nil unless ps.valid_syntax?

  ps.ast.to_s
rescue StandardError
  nil
end

Tok = Struct.new(:line, :col, :type, :str, :off)

def lex(src)
  starts = [0]
  src.each_char.with_index { |ch, i| starts << i + 1 if ch == "\n" }
  Ripper.lex(src).map do |(pos, type, str, _state)|
    Tok.new(pos[0], pos[1], type, str, starts[pos[0] - 1] + byte_to_char(src, starts[pos[0] - 1], pos[1]))
  end
rescue StandardError
  []
end

def byte_to_char(src, line_start, byte_col)
  line = src[line_start..]
  line.byteslice(0, byte_col).to_s.force_encoding('UTF-8').length
end

def splice(src, off, len, text)
  src[0...off] + text + src[(off + len)..]
end

def line_starts(src)
  s = [0]
  src.each_char.with_index { |ch, i| s << i + 1 if ch == "\n" }
  s
end

OPEN = %i[on_lparen on_lbracket on_lbrace on_tlambeg].freeze
CLOSE = %i[on_rparen on_rbracket on_rbrace].freeze

OPS = {
  'sp_del' => 10, 'sp_add' => 10, 'sp_widen' => 6, 'indent' => 12, 'blank_add' => 6, 'blank_del' => 4,
  'trailing_ws' => 3, 'nl_after_open' => 5, 'nl_after_comma' => 5, 'nl_before_close' => 5, 'join_line' => 6,
  'dot_newline' => 4, 'comment_space' => 4, 'body_blank' => 5, 'tab_indent' => 1, 'eof' => 1, 'semicolon_sp' => 2
}.freeze

def pick_op(rng)
  total = OPS.values.sum
  r = rng.rand(total)
  OPS.each do |k, w|
    return k if r < w

    r -= w
  end
end

def code_toks(toks)
  toks.reject { |t| %i[on_sp on_nl on_ignored_nl on_comment on_tstring_content on_heredoc_end].include?(t.type) }
end

def try_op(op, src, toks, rng)
  case op
  when 'sp_del'
    c = toks.select { |t| t.type == :on_sp && t.col.positive? && !t.str.include?("\\") }
    t = c.sample(random: rng) or return nil
    splice(src, t.off, t.str.length, '')
  when 'sp_add'
    pairs = toks.each_cons(2).select do |a, b|
      a.line == b.line && !%i[on_sp on_nl on_ignored_nl on_tstring_content on_tstring_beg on_heredoc_end].include?(a.type) &&
        !%i[on_sp on_nl on_ignored_nl on_tstring_content on_tstring_end].include?(b.type)
    end
    pair = pairs.sample(random: rng) or return nil
    b = pair[1]
    splice(src, b.off, 0, ' ' * [1, 1, 1, 2].sample(random: rng))
  when 'sp_widen'
    t = toks.select { |x| x.type == :on_sp && x.col.positive? && !x.str.include?("\\") }.sample(random: rng) or return nil
    splice(src, t.off, t.str.length, ' ' * (2 + rng.rand(3)))
  when 'indent', 'tab_indent'
    t = toks.select { |x| x.type == :on_sp && x.col.zero? }.sample(random: rng)
    starts = line_starts(src)
    if t.nil? || rng.rand < 0.25
      ln = rng.rand(starts.size - 1)
      off = starts[ln]
      return nil if src[off] == "\n" || src[off].nil?

      return splice(src, off, 0, op == 'tab_indent' ? "\t" : ' ' * (1 + rng.rand(4)))
    end
    if op == 'tab_indent'
      splice(src, t.off, t.str.length, "\t" * [t.str.length / 2, 1].max)
    else
      delta = [-4, -2, -1, 1, 2, 4].sample(random: rng)
      n = [t.str.length + delta, 0].max
      splice(src, t.off, t.str.length, ' ' * n)
    end
  when 'blank_add', 'body_blank'
    nls = toks.select { |x| %i[on_nl on_ignored_nl].include?(x.type) }
    if op == 'body_blank'
      openers = toks.each_cons(2).select do |a, b|
        %i[on_nl on_ignored_nl].include?(b.type) && (a.type == :on_kw && %w[do begin then else ensure].include?(a.str) ||
          a.type == :on_rparen || a.type == :on_const || a.type == :on_ident || a.type == :on_op && a.str == '|')
      end.map(&:last)
      ends = toks.each_cons(2).select { |a, b| a.type == :on_sp && a.col.zero? && b.type == :on_kw && b.str == 'end' }
      cand = openers + ends.map { |a, _| Tok.new(a.line, 0, :before, '', a.off) }
      t = cand.sample(random: rng) or return nil
      return splice(src, t.off, 0, "\n") if t.type == :before

      return splice(src, t.off + t.str.length, 0, "\n")
    end
    t = nls.sample(random: rng) or return nil
    splice(src, t.off + t.str.length, 0, "\n" * (1 + (rng.rand < 0.3 ? 1 : 0)))
  when 'blank_del'
    t = toks.select { |x| x.type == :on_ignored_nl && x.col.zero? }.sample(random: rng) or return nil
    splice(src, t.off, t.str.length, '')
  when 'trailing_ws'
    t = toks.select { |x| %i[on_nl on_ignored_nl].include?(x.type) }.sample(random: rng) or return nil
    splice(src, t.off, 0, [' ', '  ', "\t"].sample(random: rng))
  when 'nl_after_open', 'nl_after_comma'
    types = op == 'nl_after_open' ? OPEN : %i[on_comma]
    t = toks.select { |x| types.include?(x.type) }.sample(random: rng) or return nil
    nxt = toks.find { |x| x.off > t.off }
    return nil unless nxt

    stop = nxt.type == :on_sp ? nxt.off + nxt.str.length : t.off + t.str.length
    indent = ' ' * [t.col + [1, 2, 0].sample(random: rng), indent_of(src, t.off) + [2, 4].sample(random: rng)].sample(random: rng)
    splice(src, t.off + t.str.length, stop - t.off - t.str.length, "\n" + indent)
  when 'nl_before_close'
    t = toks.select { |x| CLOSE.include?(x.type) }.sample(random: rng) or return nil
    splice(src, t.off, 0, "\n" + ' ' * (indent_of(src, t.off) + [0, 0, 2].sample(random: rng)))
  when 'join_line'
    t = toks.each_cons(2).select do |a, b|
      %i[on_nl on_ignored_nl].include?(b.type) && (OPEN.include?(a.type) || a.type == :on_comma || a.type == :on_op ||
        a.type == :on_period || CLOSE.include?(a.type))
    end.map(&:last).sample(random: rng) or return nil
    rest = src[(t.off + t.str.length)..]
    lead = rest[/\A[ \t]*/].length
    splice(src, t.off, t.str.length + lead, [' ', ''].sample(random: rng))
  when 'dot_newline'
    t = toks.select { |x| %i[on_period on_op].include?(x.type) && (x.str == '.' || x.str == '&.') }.sample(random: rng) or return nil
    if rng.rand < 0.5
      splice(src, t.off, 0, "\n" + ' ' * (indent_of(src, t.off) + [2, 4, 0].sample(random: rng)))
    else
      splice(src, t.off + t.str.length, 0, "\n" + ' ' * (indent_of(src, t.off) + [2, 4].sample(random: rng)))
    end
  when 'comment_space'
    t = toks.select { |x| x.type == :on_comment && !x.str.start_with?('#!') && !x.str.match?(/\A#\s*(frozen_string_literal|encoding|rubocop:)/) }.sample(random: rng) or return nil
    body = t.str.sub(/\A#+/, '')
    hashes = t.str[/\A#+/]
    new = case rng.rand(4)
          when 0 then hashes + body.lstrip
          when 1 then hashes + '   ' + body.lstrip
          when 2 then hashes + body.rstrip.sub(/\S.*\z/m) { |m| m } + "  "
          else hashes + "\t" + body.lstrip
          end
    new = new.chomp + (t.str.end_with?("\n") ? "\n" : '')
    splice(src, t.off, t.str.length, new)
  when 'eof'
    case rng.rand(3)
    when 0 then src.sub(/\n*\z/, "\n" * (2 + rng.rand(2)))
    when 1 then src.sub(/\n+\z/, '')
    else "\n" * (1 + rng.rand(2)) + src
    end
  when 'semicolon_sp'
    t = toks.select { |x| x.type == :on_semicolon || (x.type == :on_op && %w[= == + - * || && => <=>].include?(x.str)) }.sample(random: rng) or return nil
    case rng.rand(3)
    when 0 then splice(src, t.off, 0, ' ')
    when 1 then splice(src, t.off + t.str.length, 0, ' ')
    else
      after = src[(t.off + t.str.length)..][/\A */].length
      splice(src, t.off + t.str.length, after, '')
    end
  end
end

def indent_of(src, off)
  ls = src.rindex("\n", off - 1)
  start = ls ? ls + 1 : 0
  src[start..][/\A */].length
end

STDIN.each_line do |line|
  job = JSON.parse(line)
  src = job['source']
  rng = Random.new(job['seed'])
  base = ast_of(src)
  applied = []
  if base
    attempts = 0
    while applied.size < job['count'] && attempts < job['count'] * 12
      attempts += 1
      op = pick_op(rng)
      toks = lex(src)
      break if toks.empty?

      cand = begin
        try_op(op, src, toks, rng)
      rescue StandardError
        nil
      end
      next if cand.nil? || cand == src
      next unless ast_of(cand) == base

      src = cand
      applied << op
    end
  end
  puts JSON.generate({ 'id' => job['id'], 'source' => src, 'applied' => applied, 'ok' => !base.nil? })
  $stdout.flush
end
