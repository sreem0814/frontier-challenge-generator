// match_shim.cpp: the few libllama symbols llama-grammar.cpp references, for a grammar-only matcher build.
// The matcher never passes a vocabulary, so the vocabulary members are unreachable.
#include "llama-impl.h"
#include "llama-vocab.h"

#include <cstdarg>
#include <cstdio>
#include <cstdlib>

void llama_log_internal(ggml_log_level, const char *, ...) {}

int32_t llama_vocab::tokenize(const char *, int32_t, llama_token *, int32_t, bool, bool) const { abort(); }
const std::string & llama_vocab::token_to_piece(llama_token) const { abort(); }
bool llama_vocab::is_eog(llama_token) const { abort(); }

extern "C" void ggml_abort(const char *, int, const char *, ...) { abort(); }
