// case_runner: runs grammar and JSON-schema cases against the library built from this tree and prints one framed
// transcript per case.
//
//   case_runner <cases.txt> [--models DIR] [--timeout SECONDS] [--only ID]
//
// Case file: blocks of
//   CASE <id> <bucket> <kind>
//   <key> <args...>            (text arguments are hex-encoded bytes)
//   END
// Output per case: "C <id> <bucket> <n>\n" followed by n bytes of transcript, or "X <id> <bucket> <reason>\n" when
// the case crashed or ran out of time. Every case runs in its own forked process.
//
// Kinds:
//   P  parse       G <grammar>...                       parse result, symbol ids, rule elements, printed form, init
//   M  match       G <grammar> [R <root>] S <string>... per string: ACCEPT, PREFIX or REJECT <index>
//   S  stacks      G <grammar> [R <root>] S <string>    the set of stacks after init and after each code point
//   T  tokens      V <vocab> G <grammar> [R <root>] [L 1] [TP <pattern>]... [TT <id>]... then script ops:
//                  A | K <id> | Z <text> | N <count> <seed> | C | U <text>
//   D  schema doc  J <json>...                          the parsed schema document, or THROW
//   X  schema text J <json> | F <literal> | B ops       converter output text, or THROW
//   L  schema lang J <json>                             converter output text (scored by language, not text)
#include "llama.h"
#include "llama-grammar.h"
#ifndef MATCH_ONLY
#include "json.h"
#include "json-schema.h"
#include "json-schema-to-grammar.h"
#endif

#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>
#include <signal.h>

#include <algorithm>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct Case {
    std::string id, bucket, kind;
    std::vector<std::vector<std::string>> lines;
};

std::string unhex(const std::string & h) {
    std::string out;
    out.reserve(h.size() / 2);
    for (size_t i = 0; i + 1 < h.size(); i += 2) {
        out.push_back((char) std::stoi(h.substr(i, 2), nullptr, 16));
    }
    return out;
}

std::string hex(const std::string & s) {
    static const char * d = "0123456789abcdef";
    std::string out;
    for (unsigned char c : s) {
        out.push_back(d[c >> 4]);
        out.push_back(d[c & 15]);
    }
    return out;
}

std::vector<std::string> split_ws(const std::string & line) {
    std::vector<std::string> out;
    std::istringstream is(line);
    std::string w;
    while (is >> w) {
        out.push_back(w);
    }
    return out;
}

std::vector<Case> read_cases(const char * path) {
    std::ifstream f(path);
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        exit(2);
    }
    std::vector<Case> cases;
    std::string line;
    Case cur;
    bool in = false;
    while (std::getline(f, line)) {
        auto w = split_ws(line);
        if (w.empty()) {
            continue;
        }
        if (w[0] == "CASE" && w.size() >= 4) {
            cur = Case{w[1], w[2], w[3], {}};
            in = true;
        } else if (w[0] == "END") {
            if (in) {
                cases.push_back(cur);
            }
            in = false;
        } else if (in) {
            cur.lines.push_back(w);
        }
    }
    return cases;
}

// UTF-8 to code points, the harness's own decoder (invalid bytes become U+FFFD so inputs stay well defined)
std::vector<uint32_t> code_points(const std::string & s) {
    std::vector<uint32_t> out;
    size_t i = 0;
    while (i < s.size()) {
        unsigned char c = s[i];
        int n = c < 0x80 ? 1 : (c >> 5) == 6 ? 2 : (c >> 4) == 14 ? 3 : (c >> 3) == 30 ? 4 : 0;
        if (n == 0 || i + n > s.size()) {
            out.push_back(0xFFFD);
            i++;
            continue;
        }
        uint32_t v = n == 1 ? c : n == 2 ? (c & 0x1F) : n == 3 ? (c & 0x0F) : (c & 0x07);
        bool ok = true;
        for (int k = 1; k < n; k++) {
            unsigned char cc = s[i + k];
            if ((cc & 0xC0) != 0x80) {
                ok = false;
                break;
            }
            v = (v << 6) | (cc & 0x3F);
        }
        if (!ok) {
            out.push_back(0xFFFD);
            i++;
            continue;
        }
        out.push_back(v);
        i += n;
    }
    return out;
}

struct Out {
    std::string s;
    void line(const std::string & t) { s += t; s += '\n'; }
    void fmt(const char * f, ...) __attribute__((format(printf, 2, 3))) {
        char buf[4096];
        va_list ap;
        va_start(ap, f);
        int n = vsnprintf(buf, sizeof buf, f, ap);
        va_end(ap);
        if (n >= (int) sizeof buf) {
            std::vector<char> big(n + 1);
            va_start(ap, f);
            vsnprintf(big.data(), big.size(), f, ap);
            va_end(ap);
            s.append(big.data(), n);
        } else if (n > 0) {
            s.append(buf, n);
        }
    }
};

std::string arg(const Case & c, const std::string & key, const std::string & def = "") {
    for (const auto & w : c.lines) {
        if (!w.empty() && w[0] == key) {
            return w.size() >= 2 ? unhex(w[1]) : std::string();
        }
    }
    return def;
}

// hex argument i of a line, empty when the line has no such argument (an empty string encodes as nothing)
std::string wa(const std::vector<std::string> & w, size_t i) {
    return w.size() > i ? unhex(w[i]) : std::string();
}

std::string raw(const Case & c, const std::string & key) {
    for (const auto & w : c.lines) {
        if (w.size() >= 2 && w[0] == key) {
            return w[1];
        }
    }
    return "";
}

std::vector<std::string> args(const Case & c, const std::string & key) {
    std::vector<std::string> out;
    for (const auto & w : c.lines) {
        if (!w.empty() && w[0] == key) {
            out.push_back(w.size() >= 2 ? unhex(w[1]) : std::string());
        }
    }
    return out;
}

llama_grammar * init(const std::string & g, const std::string & root, const llama_vocab * vocab = nullptr,
                     bool lazy = false, const std::vector<std::string> & patterns = {},
                     const std::vector<llama_token> & tokens = {}) {
    std::vector<const char *> pp;
    for (const auto & p : patterns) {
        pp.push_back(p.c_str());
    }
    return llama_grammar_init_impl(vocab, g.c_str(), root.c_str(), lazy, pp.empty() ? nullptr : pp.data(), pp.size(),
                                   tokens.empty() ? nullptr : tokens.data(), tokens.size());
}

// stack element pointer -> "rule.offset" inside the grammar's own rules
std::string elem_pos(const llama_grammar_rules & rules, const llama_grammar_element * p) {
    for (size_t r = 0; r < rules.size(); r++) {
        if (!rules[r].empty() && p >= rules[r].data() && p < rules[r].data() + rules[r].size()) {
            return std::to_string(r) + "." + std::to_string(p - rules[r].data());
        }
    }
    return "?";
}

std::vector<std::string> stack_set(llama_grammar * g) {
    const auto & rules = llama_grammar_get_rules(g);
    std::set<std::string> uniq;
    std::vector<std::string> all;
    for (const auto & st : llama_grammar_get_stacks(g)) {
        std::string s = "[";
        for (size_t i = 0; i < st.size(); i++) {
            s += (i ? " " : "") + elem_pos(rules, st[i]);
        }
        s += "]";
        all.push_back(s);
    }
    std::sort(all.begin(), all.end());
    return all;
}

bool any_empty_stack(llama_grammar * g) {
    for (const auto & st : llama_grammar_get_stacks(g)) {
        if (st.empty()) {
            return true;
        }
    }
    return false;
}

// ---------------------------------------------------------------- P: parse
void run_parse(const Case & c, Out & o) {
    int k = 0;
    for (const auto & g : args(c, "G")) {
        o.fmt("grammar %d\n", k++);
        llama_grammar_parser parser;
        bool ok = parser.parse(g.c_str());
        o.fmt("parse %d\n", ok ? 1 : 0);
        if (ok) {
            std::vector<std::pair<uint32_t, std::string>> syms;
            for (const auto & kv : parser.symbol_ids) {
                syms.push_back({kv.second, kv.first});
            }
            std::sort(syms.begin(), syms.end());
            for (const auto & s : syms) {
                o.fmt("sym %u %s\n", s.first, s.second.c_str());
            }
            for (size_t r = 0; r < parser.rules.size(); r++) {
                o.fmt("rule %zu:", r);
                for (const auto & e : parser.rules[r]) {
                    o.fmt(" %d:%u", (int) e.type, e.value);
                }
                o.line("");
            }
            char * buf = nullptr;
            size_t len = 0;
            FILE * mf = open_memstream(&buf, &len);
            parser.print(mf);
            fclose(mf);
            o.line("print:");
            o.s.append(buf ? buf : "", len);
            o.line("end print");
            free(buf);
        }
        llama_grammar * gr = init(g, "root");
        o.fmt("init %d\n", gr ? 1 : 0);
        llama_grammar_free_impl(gr);
    }
}

// ---------------------------------------------------------------- M: match
std::string match_one(const std::string & g, const std::string & root, const std::string & s) {
    llama_grammar * gr = init(g, root);
    if (!gr) {
        return "INIT_FAIL";
    }
    std::string verdict;
    auto cps = code_points(s);
    for (size_t i = 0; i < cps.size(); i++) {
        llama_grammar_accept(gr, cps[i]);
        if (llama_grammar_get_stacks(gr).empty()) {
            verdict = "REJECT " + std::to_string(i);
            break;
        }
    }
    if (verdict.empty()) {
        verdict = any_empty_stack(gr) ? "ACCEPT" : "PREFIX";
    }
    llama_grammar_free_impl(gr);
    return verdict;
}

void run_match(const Case & c, Out & o) {
    std::string g = arg(c, "G"), root = arg(c, "R", "root");
    llama_grammar * gr = init(g, root);
    o.fmt("init %d\n", gr ? 1 : 0);
    if (!gr) {
        return;
    }
    llama_grammar_free_impl(gr);
    int k = 0;
    for (const auto & s : args(c, "S")) {
        o.fmt("%d %s\n", k++, match_one(g, root, s).c_str());
    }
}

// ---------------------------------------------------------------- S: stacks
void run_stacks(const Case & c, Out & o) {
    std::string g = arg(c, "G"), root = arg(c, "R", "root");
    llama_grammar * gr = init(g, root);
    o.fmt("init %d\n", gr ? 1 : 0);
    if (!gr) {
        return;
    }
    auto dump = [&](const char * label) {
        auto ss = stack_set(gr);
        o.fmt("%s %zu\n", label, ss.size());
        for (const auto & s : ss) {
            o.line("  " + s);
        }
    };
    dump("start");
    auto cps = code_points(arg(c, "S"));
    for (size_t i = 0; i < cps.size(); i++) {
        llama_grammar_accept(gr, cps[i]);
        char label[64];
        snprintf(label, sizeof label, "after %zu U+%04X", i, cps[i]);
        dump(label);
        if (llama_grammar_get_stacks(gr).empty()) {
            break;
        }
    }
    llama_grammar_free_impl(gr);
}

#ifndef MATCH_ONLY
// ---------------------------------------------------------------- T: tokens
std::map<std::string, llama_model *> g_models;
std::string g_models_dir = "models";

const llama_vocab * get_vocab(const std::string & name) {
    auto it = g_models.find(name);
    if (it == g_models.end()) {
        auto mp = llama_model_default_params();
        mp.vocab_only = true;
        std::string path = g_models_dir + "/ggml-vocab-" + name + ".gguf";
        llama_model * m = llama_model_load_from_file(path.c_str(), mp);
        it = g_models.emplace(name, m).first;
    }
    return it->second ? llama_model_get_vocab(it->second) : nullptr;
}

uint64_t fnv(uint64_t h, uint32_t v) {
    for (int i = 0; i < 4; i++) {
        h ^= (v >> (8 * i)) & 0xFF;
        h *= 1099511628211ull;
    }
    return h;
}

std::vector<llama_token> allowed_tokens(llama_grammar * gr, int n_vocab) {
    std::vector<llama_token_data> data(n_vocab);
    for (int i = 0; i < n_vocab; i++) {
        data[i] = {i, 0.0f, 0.0f};
    }
    llama_token_data_array arr = {data.data(), data.size(), -1, false};
    llama_grammar_apply_impl(*gr, &arr);
    std::vector<llama_token> ok;
    for (size_t i = 0; i < arr.size; i++) {
        if (arr.data[i].logit != -INFINITY) {
            ok.push_back(arr.data[i].id);
        }
    }
    std::sort(ok.begin(), ok.end());
    return ok;
}

void report_allowed(Out & o, const std::vector<llama_token> & ok) {
    uint64_t h = 1469598103934665603ull;
    for (auto t : ok) {
        h = fnv(h, (uint32_t) t);
    }
    o.fmt("allowed %zu %016llx", ok.size(), (unsigned long long) h);
    if (ok.size() <= 24) {
        for (auto t : ok) {
            o.fmt(" %d", t);
        }
    }
    o.line("");
}

void report_state(Out & o, llama_grammar * gr) {
    o.fmt("state awaiting=%d stacks=%zu empty=%d partial=%u/%d buf=%s\n", gr->awaiting_trigger ? 1 : 0,
          llama_grammar_get_stacks(gr).size(), any_empty_stack(gr) ? 1 : 0, gr->partial_utf8.value,
          gr->partial_utf8.n_remain, hex(gr->trigger_buffer).c_str());
}

void run_tokens(const Case & c, Out & o) {
    const llama_vocab * vocab = get_vocab(arg(c, "V"));
    if (!vocab) {
        o.line("vocab missing");
        return;
    }
    const int n_vocab = llama_vocab_n_tokens(vocab);
    std::vector<llama_token> trig_tokens;
    for (const auto & w : c.lines) {
        if (w.size() >= 2 && w[0] == "TT") {
            trig_tokens.push_back(std::stoi(w[1]));
        }
    }
    bool lazy = raw(c, "L") == "1";
    llama_grammar * gr = init(arg(c, "G"), arg(c, "R", "root"), vocab, lazy, args(c, "TP"), trig_tokens);
    o.fmt("init %d\n", gr ? 1 : 0);
    if (!gr) {
        return;
    }
    auto accept = [&](llama_token t) -> bool {
        o.fmt("accept %d\n", t);
        try {
            llama_grammar_accept_impl(*gr, t);
        } catch (const std::exception &) {
            o.line("exception");
            return false;
        }
        report_state(o, gr);
        return true;
    };
    report_state(o, gr);
    for (const auto & w : c.lines) {
        const std::string & op = w[0];
        if (op == "A") {
            report_allowed(o, allowed_tokens(gr, n_vocab));
        } else if (op == "K" && w.size() >= 2) {
            if (!accept(std::stoi(w[1]))) {
                break;
            }
        } else if (op == "Z") {
            std::string text = wa(w, 1);
            std::vector<llama_token> toks(text.size() + 8);
            int n = llama_tokenize(vocab, text.c_str(), (int32_t) text.size(), toks.data(), (int32_t) toks.size(),
                                   false, true);
            toks.resize(std::max(n, 0));
            bool stop = false;
            for (auto t : toks) {
                auto ok = allowed_tokens(gr, n_vocab);
                bool allowed = std::binary_search(ok.begin(), ok.end(), t);
                o.fmt("token %d allowed=%d of %zu\n", t, allowed ? 1 : 0, ok.size());
                if (!allowed) {
                    stop = true;
                    break;
                }
                if (!accept(t)) {
                    stop = true;
                    break;
                }
            }
            if (stop) {
                break;
            }
        } else if (op == "N" && w.size() >= 3) {
            int count = std::stoi(w[1]);
            uint64_t seed = std::stoull(w[2]);
            bool stop = false;
            for (int i = 0; i < count && !stop; i++) {
                auto ok = allowed_tokens(gr, n_vocab);
                report_allowed(o, ok);
                std::vector<llama_token> pick;
                for (auto t : ok) {
                    if (!llama_vocab_is_eog(vocab, t)) {
                        pick.push_back(t);
                    }
                }
                if (pick.empty()) {
                    break;
                }
                seed = seed * 6364136223846793005ull + 1442695040888963407ull;
                llama_token t = pick[(seed >> 33) % pick.size()];
                stop = !accept(t);
            }
            if (stop) {
                break;
            }
        } else if (op == "C") {
            llama_grammar * cl = llama_grammar_clone_impl(*gr);
            llama_grammar_free_impl(gr);
            gr = cl;
            o.line("clone");
            report_state(o, gr);
        } else if (op == "U") {
            o.fmt("accept_str %s\n", hex(wa(w, 1)).c_str());
            try {
                llama_grammar_accept_str(*gr, wa(w, 1));
            } catch (const std::exception &) {
                o.line("exception");
                break;
            }
            report_state(o, gr);
        }
    }
    llama_grammar_free_impl(gr);
}

// ---------------------------------------------------------------- D: schema document
struct DocDumper {
    const common_chat_schema_document & doc;
    Out & o;

    std::string ref_key(const common_chat_schema * target) {
        if (!target) {
            return "(null)";
        }
        for (const auto & kv : doc.refs) {
            if (kv.second.get() == target) {
                return kv.first;
            }
        }
        return "(unknown)";
    }

    void node(const common_chat_schema * s, int depth) {
        std::string ind(depth * 2, ' ');
        if (!s) {
            o.line(ind + "(null)");
            return;
        }
        uint32_t mask = 0;
        auto ts = s->value_types();
        for (int t = 0; t <= common_chat_schema::TYPE_OBJECT; t++) {
            if (ts.has((common_chat_schema::value_type) t)) {
                mask |= 1u << t;
            }
        }
        o.fmt("%skind %d types %02x str %d", ind.c_str(), (int) s->kind(), mask, s->may_be_string() ? 1 : 0);
        switch (s->kind()) {
            case common_chat_schema::KIND_REF: {
                auto & r = static_cast<const common_chat_schema_ref &>(*s);
                o.fmt(" ref %s -> %s\n", hex(r.ref).c_str(), hex(ref_key(r.target)).c_str());
                break;
            }
            case common_chat_schema::KIND_ANY_OF:
            case common_chat_schema::KIND_ALL_OF: {
                const auto & ch = s->kind() == common_chat_schema::KIND_ANY_OF
                    ? static_cast<const common_chat_schema_any_of &>(*s).children
                    : static_cast<const common_chat_schema_all_of &>(*s).children;
                o.fmt(" n %zu\n", ch.size());
                for (const auto & c : ch) {
                    node(c.get(), depth + 1);
                }
                break;
            }
            case common_chat_schema::KIND_CONST:
                o.fmt(" value %s\n", hex(static_cast<const common_chat_schema_const &>(*s).value.dump()).c_str());
                break;
            case common_chat_schema::KIND_ENUM: {
                const auto & vs = static_cast<const common_chat_schema_enum &>(*s).values;
                o.fmt(" n %zu", vs.size());
                for (const auto & v : vs) {
                    o.fmt(" %s", hex(v.dump()).c_str());
                }
                o.line("");
                break;
            }
            case common_chat_schema::KIND_INTEGER: {
                auto & n = static_cast<const common_chat_schema_integer &>(*s);
                o.fmt(" min %lld max %lld\n", (long long) n.minimum, (long long) n.maximum);
                break;
            }
            case common_chat_schema::KIND_STRING: {
                auto & n = static_cast<const common_chat_schema_string &>(*s);
                o.fmt(" pattern %s format %d len %d %d\n", hex(n.pattern).c_str(), (int) n.format, n.min_length,
                      n.max_length);
                break;
            }
            case common_chat_schema::KIND_ARRAY: {
                auto & n = static_cast<const common_chat_schema_array &>(*s);
                o.fmt(" items %d %d\n", n.min_items, n.max_items);
                node(n.items.get(), depth + 1);
                break;
            }
            case common_chat_schema::KIND_TUPLE: {
                auto & n = static_cast<const common_chat_schema_tuple &>(*s);
                o.fmt(" n %zu\n", n.items.size());
                for (const auto & c : n.items) {
                    node(c.get(), depth + 1);
                }
                break;
            }
            case common_chat_schema::KIND_OBJECT: {
                auto & n = static_cast<const common_chat_schema_object &>(*s);
                o.fmt(" props %zu additional %d\n", n.properties.size(), n.additional_properties ? 1 : 0);
                for (const auto & p : n.properties) {
                    o.fmt("%s  prop %s required %d\n", ind.c_str(), hex(p.name).c_str(), p.required ? 1 : 0);
                    node(p.schema.get(), depth + 2);
                }
                if (n.additional_properties) {
                    o.line(ind + "  additional");
                    node(n.additional_properties.get(), depth + 2);
                }
                break;
            }
            default:
                o.line("");
        }
    }
};

void run_doc(const Case & c, Out & o) {
    int k = 0;
    for (const auto & j : args(c, "J")) {
        o.fmt("schema %d\n", k++);
        common_json js = common_json::parse(j);
        try {
            common_chat_schema_document doc = common_chat_schema_from_json(js);
            DocDumper d{doc, o};
            o.line("root");
            d.node(doc.root.get(), 1);
            for (const auto & kv : doc.refs) {
                o.fmt("def %s\n", hex(kv.first).c_str());
                d.node(kv.second.get(), 1);
            }
        } catch (const std::exception &) {
            o.line("THROW");
        }
    }
}

// ---------------------------------------------------------------- X / L: converter output
std::string convert(const std::string & j, bool & threw) {
    threw = false;
    common_json js = common_json::parse(j);
    try {
        return json_schema_to_grammar(js, true);
    } catch (const std::exception &) {
        threw = true;
        return "";
    }
}

void run_text(const Case & c, Out & o) {
    int k = 0;
    for (const auto & w : c.lines) {
        if (w[0] == "J") {
            bool threw;
            std::string g = convert(wa(w, 1), threw);
            o.fmt("schema %d\n", k++);
            if (threw) {
                o.line("THROW");
            } else {
                o.s += g;
                o.line("end grammar");
            }
        } else if (w[0] == "F") {
            o.line("literal " + hex(gbnf_format_literal(wa(w, 1))));
        }
    }
    // build_grammar script: BR <name> <rule> | BS <name> <json>, optional BD 1 for dotall
    bool any_b = false;
    for (const auto & w : c.lines) {
        any_b = any_b || w[0] == "BR" || w[0] == "BS";
    }
    if (any_b) {
        common_grammar_options opts;
        opts.dotall = raw(c, "BD") == "1";
        std::vector<common_chat_schema_document> docs;
        docs.reserve(c.lines.size());
        try {
            std::string g = build_grammar([&](const common_grammar_builder & b) {
                for (const auto & w : c.lines) {
                    if (w[0] == "BR") {
                        o.line("rule " + hex(b.add_rule(wa(w, 1), wa(w, 2))));
                    } else if (w[0] == "BS") {
                        docs.push_back(common_chat_schema_from_json(common_json::parse(wa(w, 2))));
                        o.line("schema " + hex(b.add_schema(wa(w, 1), *docs.back().root)));
                    }
                }
            }, opts);
            o.s += g;
            o.line("end grammar");
        } catch (const std::exception &) {
            o.line("THROW");
        }
    }
}

void run_lang(const Case & c, Out & o) {
    bool threw;
    std::string g = convert(arg(c, "J"), threw);
    if (threw) {
        o.line("THROW");
    } else {
        o.line("OK");
        o.s += g;
    }
}

#endif  // MATCH_ONLY

void run_case(const Case & c, Out & o) {
#ifdef MATCH_ONLY
    if (c.kind == "M") {
        run_match(c, o);
    } else {
        o.line("unknown kind");
    }
#else
    if (c.kind == "P") {
        run_parse(c, o);
    } else if (c.kind == "M") {
        run_match(c, o);
    } else if (c.kind == "S") {
        run_stacks(c, o);
    } else if (c.kind == "T") {
        run_tokens(c, o);
    } else if (c.kind == "D") {
        run_doc(c, o);
    } else if (c.kind == "X") {
        run_text(c, o);
    } else if (c.kind == "L") {
        run_lang(c, o);
    } else {
        o.line("unknown kind");
    }
#endif
}

#ifndef MATCH_ONLY
void quiet_log(enum ggml_log_level, const char *, void *) {}
#endif

}  // namespace

int main(int argc, char ** argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <cases.txt> [--models DIR] [--timeout SECONDS] [--only ID]\n", argv[0]);
        return 2;
    }
    int timeout = 10;
    std::string only;
    for (int i = 2; i + 1 < argc; i += 2) {
        if (!strcmp(argv[i], "--models")) {
#ifndef MATCH_ONLY
            g_models_dir = argv[i + 1];
#endif
        } else if (!strcmp(argv[i], "--timeout")) {
            timeout = atoi(argv[i + 1]);
        } else if (!strcmp(argv[i], "--only")) {
            only = argv[i + 1];
        }
    }
    auto cases = read_cases(argv[1]);
#ifndef MATCH_ONLY
    llama_log_set(quiet_log, nullptr);
    llama_backend_init();
    // vocabularies load once in the parent, so every forked case shares them
    for (const auto & c : cases) {
        if (c.kind == "T" && (only.empty() || only == c.id)) {
            get_vocab(arg(c, "V"));
        }
    }
#endif
    for (const auto & c : cases) {
        if (!only.empty() && c.id != only) {
            continue;
        }
        fflush(stdout);
        int fds[2];
        if (pipe(fds) != 0) {
            return 3;
        }
        pid_t pid = fork();
        if (pid == 0) {
            close(fds[0]);
            alarm(timeout);
            struct rlimit rl = {(rlim_t) 4 << 30, (rlim_t) 4 << 30};
            setrlimit(RLIMIT_AS, &rl);
            if (only.empty()) {
                freopen("/dev/null", "w", stderr);
            }
            Out o;
            run_case(c, o);
            size_t off = 0;
            while (off < o.s.size()) {
                ssize_t n = write(fds[1], o.s.data() + off, o.s.size() - off);
                if (n <= 0) {
                    break;
                }
                off += n;
            }
            close(fds[1]);
            _exit(0);
        }
        close(fds[1]);
        std::string data;
        char buf[65536];
        ssize_t n;
        while ((n = read(fds[0], buf, sizeof buf)) > 0) {
            data.append(buf, n);
        }
        close(fds[0]);
        int st = 0;
        waitpid(pid, &st, 0);
        if (WIFEXITED(st) && WEXITSTATUS(st) == 0) {
            printf("C %s %s %zu\n", c.id.c_str(), c.bucket.c_str(), data.size());
            fwrite(data.data(), 1, data.size(), stdout);
        } else if (WIFSIGNALED(st) && WTERMSIG(st) == SIGALRM) {
            printf("X %s %s timeout\n", c.id.c_str(), c.bucket.c_str());
        } else {
            printf("X %s %s crash\n", c.id.c_str(), c.bucket.c_str());
        }
    }
    fflush(stdout);
#ifndef MATCH_ONLY
    for (auto & kv : g_models) {
        if (kv.second) {
            llama_model_free(kv.second);
        }
    }
#endif
    return 0;
}
