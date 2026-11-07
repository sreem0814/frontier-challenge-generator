// JSON schema documents: common_chat_schema_from_json() and the node queries declared in json-schema.h.
// The implementation was removed from this tree. Rebuild it behind the declarations in json-schema.h.
#include "json-schema.h"
#include "common.h"

#include <stdexcept>

common_chat_schema_document common_chat_schema_from_json(const common_json & schema) {
    (void) schema;
    throw std::runtime_error("JSON schema support is not implemented");
}

common_chat_schema::type_set common_chat_schema::value_types() const {
    return {};
}

bool common_chat_schema::may_be_string() const {
    return false;
}

const char * common_chat_schema::kind_name(node_kind kind) {
    (void) kind;
    return "?";
}

const char * common_chat_schema::type_name(value_type type) {
    (void) type;
    return "?";
}
