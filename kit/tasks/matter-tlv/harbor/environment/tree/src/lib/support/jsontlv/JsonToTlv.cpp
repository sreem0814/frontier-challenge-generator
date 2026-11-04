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

#include <stdint.h>
#include <algorithm>
#include <charconv>
#include <sstream>
#include <string>
#include <vector>
#include <json/json.h>
#include <lib/support/Base64.h>
#include <lib/support/SafeInt.h>
#include <lib/support/jsontlv/ElementTypes.h>
#include <lib/support/jsontlv/JsonToTlv.h>

namespace chip {
CHIP_ERROR JsonToTlv(const std::string & jsonString, MutableByteSpan & tlv)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR JsonToTlv(const std::string & jsonString, TLV::TLVWriter & writer)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR ConvertTlvTag(uint32_t tagNumber, TLV::Tag & tag)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace chip
