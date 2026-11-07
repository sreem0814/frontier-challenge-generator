// GBNF grammar engine: parser, pushdown stacks, token-level constraint and lazy triggers.
// The implementation was removed from this tree. Rebuild it behind the declarations in llama-grammar.h.
// grammars/README.md describes the GBNF syntax.
#include "llama-grammar.h"

#include "llama-impl.h"
#include "llama-vocab.h"
#include "llama-sampler.h"

#include <stdexcept>

size_t llama_grammar_trigger_pattern::find(const std::string & input) const {
    (void) input;
    return std::string::npos;
}

uint32_t llama_grammar_parser::get_symbol_id(const char * src, size_t len) {
    (void) src;
    (void) len;
    return 0;
}

uint32_t llama_grammar_parser::generate_symbol_id(const std::string & base_name) {
    (void) base_name;
    return 0;
}

void llama_grammar_parser::add_rule(uint32_t rule_id, const llama_grammar_rule & rule) {
    (void) rule_id;
    (void) rule;
}

const char * llama_grammar_parser::parse_alternates(const char * src, const std::string & rule_name, uint32_t rule_id,
                                                    bool is_nested) {
    (void) rule_name;
    (void) rule_id;
    (void) is_nested;
    return src;
}

const char * llama_grammar_parser::parse_sequence(const char * src, const std::string & rule_name,
                                                  llama_grammar_rule & rule, bool is_nested) {
    (void) rule_name;
    (void) rule;
    (void) is_nested;
    return src;
}

const char * llama_grammar_parser::parse_rule(const char * src) {
    return src;
}

bool llama_grammar_parser::parse(const char * src) {
    (void) src;
    rules.clear();
    return false;
}

void llama_grammar_parser::print(FILE * file) {
    (void) file;
}

llama_grammar_stack llama_grammar_parser::c_rules() const {
    return {};
}

const llama_grammar_rules & llama_grammar_get_rules(const struct llama_grammar * grammar) {
    return grammar->rules;
}

llama_grammar_stacks & llama_grammar_get_stacks(struct llama_grammar * grammar) {
    return grammar->stacks;
}

void llama_grammar_accept(struct llama_grammar * grammar, uint32_t chr) {
    (void) chr;
    grammar->stacks.clear();
}

llama_grammar_candidates llama_grammar_reject_candidates_for_stack(const llama_grammar_rules & rules,
                                                                   const llama_grammar_stack & stack,
                                                                   const llama_grammar_candidates & candidates) {
    (void) rules;
    (void) stack;
    return candidates;
}

struct llama_grammar * llama_grammar_init_impl(const struct llama_vocab * vocab, const llama_grammar_element ** rules,
                                               size_t n_rules, size_t start_rule_index) {
    (void) vocab;
    (void) rules;
    (void) n_rules;
    (void) start_rule_index;
    return nullptr;
}

struct llama_grammar * llama_grammar_init_impl(const struct llama_vocab * vocab, const char * grammar_str,
                                               const char * grammar_root, bool lazy, const char ** trigger_patterns,
                                               size_t num_trigger_patterns, const llama_token * trigger_tokens,
                                               size_t num_trigger_tokens) {
    (void) vocab;
    (void) grammar_str;
    (void) grammar_root;
    (void) lazy;
    (void) trigger_patterns;
    (void) num_trigger_patterns;
    (void) trigger_tokens;
    (void) num_trigger_tokens;
    LLAMA_LOG_ERROR("grammar support is not implemented\n");
    return nullptr;
}

void llama_grammar_free_impl(struct llama_grammar * grammar) {
    delete grammar;
}

struct llama_grammar * llama_grammar_clone_impl(const struct llama_grammar & grammar) {
    (void) grammar;
    return nullptr;
}

void llama_grammar_apply_impl(const struct llama_grammar & grammar, llama_token_data_array * cur_p) {
    (void) grammar;
    (void) cur_p;
}

void llama_grammar_accept_impl(struct llama_grammar & grammar, llama_token token) {
    (void) grammar;
    (void) token;
    throw std::runtime_error("grammar support is not implemented");
}

void llama_grammar_accept_str(struct llama_grammar & grammar, const std::string & piece) {
    (void) grammar;
    (void) piece;
    throw std::runtime_error("grammar support is not implemented");
}

void llama_grammar_accept_token(struct llama_grammar & grammar, llama_token token, const std::string & piece) {
    (void) grammar;
    (void) token;
    (void) piece;
    throw std::runtime_error("grammar support is not implemented");
}
