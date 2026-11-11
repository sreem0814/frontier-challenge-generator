/*
 * Copyright 2014 Google Inc. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// The schema compiler front end: the .fbs and .proto parser, the JSON and
// FlexBuffers data parser, the binary schema (.bfbs) writer and reader, and the
// schema evolution check. Everything declared in include/flatbuffers/idl.h
// that is not defined inline there belongs in this file.
//
// This file is a stub. It defines only the symbols the rest of flatc links
// against, and every entry point fails, so flatc builds and runs but rejects
// every input.

#include <string>
#include <vector>

#include "flatbuffers/idl.h"

namespace flatbuffers {

const char* FLATBUFFERS_VERSION() {
  // clang-format off
  return
      FLATBUFFERS_STRING(FLATBUFFERS_VERSION_MAJOR) "."
      FLATBUFFERS_STRING(FLATBUFFERS_VERSION_MINOR) "."
      FLATBUFFERS_STRING(FLATBUFFERS_VERSION_REVISION);
  // clang-format on
}

std::string Namespace::GetFullyQualifiedName(const std::string& name,
                                             size_t /*max_components*/) const {
  return name;
}

const EnumVal* EnumDef::MinValue() const { return nullptr; }
const EnumVal* EnumDef::MaxValue() const { return nullptr; }
uint64_t EnumDef::Distance(const EnumVal*, const EnumVal*) const { return 0; }
std::string EnumDef::AllFlags() const { return "0"; }
EnumVal* EnumDef::ReverseLookup(int64_t, bool) const { return nullptr; }
EnumVal* EnumDef::FindByValue(const std::string&) const { return nullptr; }

StructDef* Parser::LookupStruct(const std::string&) const { return nullptr; }

bool Parser::Parse(const char*, const char**, const char* source_filename) {
  error_ = std::string(source_filename ? source_filename : "") +
           ": error: schema parser not implemented";
  return false;
}

bool Parser::SetRootType(const char*) { return false; }

void Parser::MarkGenerated() {}

std::vector<IncludedFile> Parser::GetIncludedFiles() const { return {}; }

std::set<std::string> Parser::GetIncludedFilesRecursive(
    const std::string&) const {
  return {};
}

void Parser::Serialize() { builder_.Clear(); }

bool Parser::Deserialize(const uint8_t*, const size_t) { return false; }

std::string Parser::ConformTo(const Parser&) {
  return "schema evolution check not implemented";
}

}  // namespace flatbuffers
