/*
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

#include "QRCodeSetupPayloadGenerator.h"
#include "Base38Encode.h"
#include <lib/core/CHIPCore.h>
#include <lib/core/TLV.h>
#include <lib/core/TLVData.h>
#include <lib/core/TLVDebug.h>
#include <lib/core/TLVUtilities.h>
#include <lib/support/CodeUtils.h>
#include <lib/support/SafeInt.h>
#include <lib/support/ScopedMemoryBuffer.h>
#include <protocols/Protocols.h>
#include <stdlib.h>
#include <string.h>
#include <string>

namespace chip {
CHIP_ERROR writeTag(TLV::TLVWriter & writer, TLV::Tag tag, OptionalQRCodeInfo & info)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR writeTag(TLV::TLVWriter & writer, TLV::Tag tag, OptionalQRCodeInfoExtension & info)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR QRCodeSetupPayloadGenerator::generateTLVFromOptionalData(SetupPayload & outPayload, uint8_t * tlvDataStart, uint32_t maxLen, size_t & tlvDataLengthInBytes)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR QRCodeSetupPayloadGenerator::payloadBase38Representation(std::string & base38Representation)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR QRCodeSetupPayloadGenerator::payloadBase38RepresentationWithAutoTLVBuffer(std::string & base38Representation)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR QRCodeSetupPayloadGenerator::payloadBase38Representation(std::string & base38Representation, uint8_t * tlvDataStart, uint32_t tlvDataStartSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR QRCodeBasicSetupPayloadGenerator::payloadBase38Representation(MutableCharSpan & outBuffer)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace chip
