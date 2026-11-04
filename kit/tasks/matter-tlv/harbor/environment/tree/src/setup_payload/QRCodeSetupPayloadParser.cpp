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

#include "QRCodeSetupPayloadParser.h"
#include "Base38Decode.h"
#include <algorithm>
#include <string.h>
#include <vector>
#include <lib/core/CHIPCore.h>
#include <lib/core/CHIPError.h>
#include <lib/core/TLVData.h>
#include <lib/core/TLVUtilities.h>
#include <lib/support/CodeUtils.h>
#include <lib/support/SafeInt.h>
#include <lib/support/ScopedMemoryBuffer.h>
#include <protocols/Protocols.h>

namespace chip {
CHIP_ERROR QRCodeSetupPayloadParser::retrieveOptionalInfos(SetupPayload & outPayload, TLV::ContiguousBufferTLVReader & reader)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR QRCodeSetupPayloadParser::parseTLVFields(SetupPayload & outPayload, uint8_t * tlvDataStart, size_t tlvDataLengthInBytes)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR QRCodeSetupPayloadParser::populateTLV(SetupPayload & outPayload, const std::vector<uint8_t> & buf, size_t & index)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

std::string QRCodeSetupPayloadParser::ExtractPayload(std::string inString)
{
    return {};
}

CHIP_ERROR QRCodeSetupPayloadParser::populatePayload(SetupPayload & outPayload)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR QRCodeSetupPayloadParser::populatePayloadFromBase38Data(std::string payload, SetupPayload & outPayload)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR QRCodeSetupPayloadParser::populatePayloads(std::vector<SetupPayload> & outPayloads) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace chip
