/*
 *
 *    Copyright (c) 2023 Project CHIP Authors
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
#include <json/json.h>
#include <lib/core/DataModelTypes.h>
#include <lib/support/Base64.h>
#include <lib/support/SafeInt.h>
#include <lib/support/jsontlv/ElementTypes.h>
#include <lib/support/jsontlv/TlvToJson.h>

namespace chip {
CHIP_ERROR TlvToJson(const ByteSpan & tlv, std::string & jsonString)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TlvToJson(TLV::TLVReader & reader, std::string & jsonString)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace chip
