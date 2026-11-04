/**
 *
 *    Copyright (c) 2020 Project CHIP Authors
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

#include "AdditionalDataPayloadParser.h"
#include <cstdlib>
#include <string.h>
#include <string>
#include <vector>
#include <lib/core/CHIPError.h>
#include <lib/core/TLVData.h>
#include <lib/core/TLVUtilities.h>
#include <lib/support/BytesToHex.h>
#include <lib/support/CodeUtils.h>
#include <protocols/Protocols.h>
#include <setup_payload/AdditionalDataPayloadGenerator.h>

namespace chip {
CHIP_ERROR AdditionalDataPayloadParser::populatePayload(SetupPayloadData::AdditionalDataPayload & outPayload)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace chip
