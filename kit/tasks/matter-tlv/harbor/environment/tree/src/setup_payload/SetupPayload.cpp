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

#include "SetupPayload.h"
#include <crypto/CHIPCryptoPAL.h>
#include <lib/core/CHIPCore.h>
#include <lib/core/CHIPVendorIdentifiers.hpp>
#include <lib/core/TLV.h>
#include <lib/core/TLVData.h>
#include <lib/core/TLVUtilities.h>
#include <lib/support/CodeUtils.h>
#include <setup_payload/ManualSetupPayloadParser.h>
#include <setup_payload/QRCodeSetupPayloadParser.h>
#include <utility>

namespace chip {
bool PayloadContents::isValidQRCodePayload(ValidationMode mode) const
{
    return false;
}

bool PayloadContents::isValidManualCode(ValidationMode mode) const
{
    return false;
}

bool PayloadContents::IsValidSetupPIN(uint32_t setupPIN)
{
    return false;
}

bool PayloadContents::CheckPayloadCommonConstraints() const
{
    return false;
}

bool PayloadContents::operator==(const PayloadContents & input) const
{
}

CHIP_ERROR SetupPayload::addOptionalVendorData(uint8_t tag, std::string data)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::addOptionalVendorData(uint8_t tag, int32_t data)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

std::vector<OptionalQRCodeInfo> SetupPayload::getAllOptionalVendorData() const
{
    return {};
}

CHIP_ERROR SetupPayload::removeOptionalVendorData(uint8_t tag)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::addSerialNumber(std::string serialNumber)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::addSerialNumber(uint32_t serialNumber)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::getSerialNumber(std::string & outSerialNumber) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::removeSerialNumber()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::generateRandomSetupPin(uint32_t & setupPINCode)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::addOptionalVendorData(const OptionalQRCodeInfo & info)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::addOptionalExtensionData(const OptionalQRCodeInfoExtension & info)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::getOptionalVendorData(uint8_t tag, OptionalQRCodeInfo & info) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR SetupPayload::getOptionalExtensionData(uint8_t tag, OptionalQRCodeInfoExtension & info) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

optionalQRCodeInfoType SetupPayload::getNumericTypeFor(uint8_t tag) const
{
    return {};
}

std::vector<OptionalQRCodeInfoExtension> SetupPayload::getAllOptionalExtensionData() const
{
    return {};
}

bool SetupPayload::operator==(const SetupPayload & input) const
{
}

CHIP_ERROR SetupPayload::FromStringRepresentation(std::string stringRepresentation, std::vector<SetupPayload> & outPayloads)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace chip
