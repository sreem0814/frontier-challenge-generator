// JSON schema to GBNF conversion: json_schema_to_grammar(), build_grammar() and gbnf_format_literal().
// The implementation was removed from this tree. Rebuild it behind the declarations in
// json-schema-to-grammar.h.
#include "json-schema-to-grammar.h"
#include "common.h"

#include <stdexcept>

std::string json_schema_to_grammar(const common_json & schema, bool force_gbnf) {
    (void) schema;
    (void) force_gbnf;
    throw std::invalid_argument("JSON schema conversion is not implemented");
}

std::string json_schema_to_grammar(const common_chat_schema_document & schema) {
    (void) schema;
    throw std::invalid_argument("JSON schema conversion is not implemented");
}

std::string gbnf_format_literal(const std::string & literal) {
    (void) literal;
    return "";
}

std::string build_grammar(const std::function<void(const common_grammar_builder &)> & cb,
                          const common_grammar_options & options) {
    (void) cb;
    (void) options;
    throw std::invalid_argument("grammar building is not implemented");
}
