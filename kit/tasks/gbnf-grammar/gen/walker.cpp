// walker: authoring tool. Produces random strings that a grammar accepts, by walking the reference engine's stacks.
//   walker <requests.txt>   blocks: CASE <id> / G <hex> / R <hex> / W <count> <seed> / END
// Output: "W <id> <hex>..." per request (fewer strings when the walk cannot terminate).
#include "llama-grammar.h"

#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <random>
#include <sstream>
#include <string>
#include <vector>

static std::string unhex(const std::string & h) {
    std::string out;
    for (size_t i = 0; i + 1 < h.size(); i += 2) out.push_back((char) std::stoi(h.substr(i, 2), nullptr, 16));
    return out;
}
static std::string hex(const std::string & s) {
    static const char * d = "0123456789abcdef";
    std::string out;
    for (unsigned char c : s) { out.push_back(d[c >> 4]); out.push_back(d[c & 15]); }
    return out;
}
static std::string utf8(uint32_t cp) {
    std::string s;
    if (cp < 0x80) s.push_back((char) cp);
    else if (cp < 0x800) { s.push_back((char) (0xC0 | (cp >> 6))); s.push_back((char) (0x80 | (cp & 0x3F))); }
    else if (cp < 0x10000) { s.push_back((char) (0xE0 | (cp >> 12))); s.push_back((char) (0x80 | ((cp >> 6) & 0x3F))); s.push_back((char) (0x80 | (cp & 0x3F))); }
    else { s.push_back((char) (0xF0 | (cp >> 18))); s.push_back((char) (0x80 | ((cp >> 12) & 0x3F))); s.push_back((char) (0x80 | ((cp >> 6) & 0x3F))); s.push_back((char) (0x80 | (cp & 0x3F))); }
    return s;
}

static bool matches(const llama_grammar_element * pos, uint32_t chr) {
    bool found = false;
    bool is_positive_char = pos->type == LLAMA_GRETYPE_CHAR || pos->type == LLAMA_GRETYPE_CHAR_ANY;
    do {
        if (pos[1].type == LLAMA_GRETYPE_CHAR_RNG_UPPER) {
            found = found || (pos->value <= chr && chr <= pos[1].value);
            pos += 2;
        } else if (pos->type == LLAMA_GRETYPE_CHAR_ANY) {
            found = true;
            pos += 1;
        } else {
            found = found || pos->value == chr;
            pos += 1;
        }
    } while (pos->type == LLAMA_GRETYPE_CHAR_ALT);
    return found == is_positive_char;
}

// candidate characters for one stack top: its own range ends plus a fixed pool
static std::vector<uint32_t> candidates(const llama_grammar_element * pos, std::mt19937_64 & rng) {
    std::vector<uint32_t> c;
    const llama_grammar_element * p = pos;
    do {
        if (p->type != LLAMA_GRETYPE_CHAR_ANY) {
            c.push_back(p->value);
            if (p[1].type == LLAMA_GRETYPE_CHAR_RNG_UPPER) {
                uint32_t lo = p->value, hi = p[1].value;
                c.push_back(hi);
                if (hi > lo) for (int k = 0; k < 3; k++) c.push_back(lo + (uint32_t) (rng() % (hi - lo + 1)));
                p += 2;
                continue;
            }
        }
        p += 1;
    } while (p->type == LLAMA_GRETYPE_CHAR_ALT || p->type == LLAMA_GRETYPE_CHAR_RNG_UPPER);
    static const uint32_t pool[] = {'a', 'z', 'Q', '0', '7', ' ', '_', '-', '.', ',', '"', '\\', '/', '{', '}', '[', ']',
                                    ':', '\t', '\n', '!', '#', 'x', 0xE9, 0x3B1, 0x4E2D, 0x1F600, 0x7F, 0x1};
    for (int k = 0; k < 6; k++) c.push_back(pool[rng() % (sizeof pool / sizeof pool[0])]);
    c.push_back(0x20 + (uint32_t) (rng() % 95));
    std::vector<uint32_t> ok;
    for (auto ch : c) if (ch != 0 && matches(pos, ch)) ok.push_back(ch);
    return ok;
}

int main(int argc, char ** argv) {
    std::ifstream f(argv[1]);
    std::string line, id, g, root = "root";
    int count = 0;
    uint64_t seed = 0;
    while (std::getline(f, line)) {
        std::istringstream is(line);
        std::string k;
        is >> k;
        if (k == "CASE") { is >> id; g.clear(); root = "root"; count = 0; }
        else if (k == "G") { std::string h; is >> h; g = unhex(h); }
        else if (k == "R") { std::string h; is >> h; root = unhex(h); }
        else if (k == "W") { is >> count >> seed; }
        else if (k == "END") {
            fflush(stdout);
            pid_t pid = fork();
            if (pid != 0) {
                int st = 0;
                waitpid(pid, &st, 0);
                if (!(WIFEXITED(st) && WEXITSTATUS(st) == 0)) {
                    printf("W %s\n", id.c_str());  // the walk crashed or ran out of time or memory: no strings
                }
                fflush(stdout);
                continue;
            }
            alarm(20);
            struct rlimit rl = {(rlim_t) 2 << 30, (rlim_t) 2 << 30};
            setrlimit(RLIMIT_AS, &rl);
            std::string buf;
            std::mt19937_64 rng(seed);
            buf += "W " + id;
            llama_grammar * base = llama_grammar_init_impl(nullptr, g.c_str(), root.c_str(), false, nullptr, 0, nullptr, 0);
            int made = 0;
            for (int attempt = 0; base && made < count && attempt < count * 8; attempt++) {
                llama_grammar * gr = llama_grammar_clone_impl(*base);
                std::string s;
                int target = 1 + (int) (rng() % (attempt % 3 == 0 ? 12 : 60));
                bool done = false;
                for (int step = 0; step < 400; step++) {
                    auto & stacks = llama_grammar_get_stacks(gr);
                    bool can_end = false;
                    std::vector<const llama_grammar_element *> tops;
                    for (auto & st : stacks) {
                        if (st.empty()) can_end = true;
                        else tops.push_back(st.back());
                    }
                    if (can_end && (tops.empty() || step >= target || rng() % 8 == 0)) { done = true; break; }
                    if (tops.empty() || stacks.size() > 4000) break;
                    const auto * top = tops[rng() % tops.size()];
                    if (top->type == LLAMA_GRETYPE_TOKEN || top->type == LLAMA_GRETYPE_TOKEN_NOT) break;
                    auto cands = candidates(top, rng);
                    if (cands.empty()) break;
                    uint32_t ch = cands[rng() % cands.size()];
                    llama_grammar_accept(gr, ch);
                    s += utf8(ch);
                    if (llama_grammar_get_stacks(gr).empty()) break;
                }
                llama_grammar_free_impl(gr);
                if (done) { buf += " " + hex(s); made++; }
            }
            if (base) llama_grammar_free_impl(base);
            buf += "\n";
            fwrite(buf.data(), 1, buf.size(), stdout);
            fflush(stdout);
            _exit(0);
        }
    }
    return 0;
}
