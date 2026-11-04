/*
 *
 *    Copyright (c) 2020-2021 Project CHIP Authors
 *    Copyright (c) 2015-2017 Nest Labs, Inc.
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

#include <lib/core/TLVUpdater.h>
#include <stdint.h>
#include <string.h>
#include <lib/core/CHIPConfig.h>
#include <lib/core/CHIPError.h>
#include <lib/core/TLVCommon.h>
#include <lib/core/TLVReader.h>
#include <lib/core/TLVTags.h>
#include <lib/core/TLVTypes.h>
#include <lib/core/TLVWriter.h>
#include <lib/support/BufferWriter.h>
#include <lib/support/CodeUtils.h>
#include <lib/support/logging/Constants.h>
#include <lib/support/logging/TextOnlyLogging.h>

namespace chip {
namespace TLV {
using namespace chip::Encoding;
CHIP_ERROR TLVUpdater::Init(uint8_t * buf, uint32_t dataLen, uint32_t maxLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVUpdater::Init(TLVReader & aReader, uint32_t freeLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

void TLVUpdater::SetImplicitProfileId(uint32_t profileId)
{
}

CHIP_ERROR TLVUpdater::Next()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVUpdater::Move()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

void TLVUpdater::MoveUntilEnd()
{
}

CHIP_ERROR TLVUpdater::EnterContainer(TLVType & outerContainerType)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVUpdater::ExitContainer(TLVType outerContainerType)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

void TLVUpdater::AdjustInternalWriterFreeSpace()
{
}

} // namespace TLV
} // namespace chip
