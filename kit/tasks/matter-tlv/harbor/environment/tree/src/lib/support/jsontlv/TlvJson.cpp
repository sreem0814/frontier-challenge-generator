/*
 *
 *    Copyright (c) 2020 Project CHIP Authors
 *    Copyright (c) 2013-2017 Nest Labs, Inc.
 *
 *    Licensed under the Apache License, Version 2.0 (the "License");
 *    you may not use this file except in compliance with the License.
 *    You may obtain a copy of the License at
 *
 *        http://www.apache.org/licenses/LICENSE-2.0
 *
 *    Unless required by applicable law or agreed to in writing, software
 *    distributed under the License is distributed on an "AS IS" BASIS,
 *    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *    See the License for the specific language governing permissions and
 *    limitations under the License.
 */

#include "lib/support/CHIPMemString.h"
#include "lib/support/ScopedMemoryBuffer.h"
#include <lib/core/DataModelTypes.h>
#include <lib/support/Base64.h>
#include <lib/support/jsontlv/TlvJson.h>

namespace chip {
std::string JsonToString(Json::Value & json)
{
    return {};
}

CHIP_ERROR TlvToJson(TLV::TLVReader & reader, Json::Value & root)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace chip
