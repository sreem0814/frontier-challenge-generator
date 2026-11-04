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

#include "ManualSetupPayloadParser.h"
#include <lib/support/SafeInt.h>
#include <lib/support/logging/CHIPLogging.h>
#include <lib/support/verhoeff/Verhoeff.h>

namespace chip {
CHIP_ERROR ManualSetupPayloadParser::CheckDecimalStringValidity(std::string decimalString, std::string & decimalStringWithoutCheckDigit)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR ManualSetupPayloadParser::CheckCodeLengthValidity(const std::string & decimalString, bool isLongCode)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR ManualSetupPayloadParser::ToNumber(const std::string & decimalString, uint32_t & dest)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR ManualSetupPayloadParser::ReadDigitsFromDecimalString(const std::string & decimalString, size_t & index, uint32_t & dest, size_t numberOfCharsToRead)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR ManualSetupPayloadParser::populatePayload(SetupPayload & outPayload)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace chip
