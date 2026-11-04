/*
 *
 *    Copyright (c) 2020-2021 Project CHIP Authors
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

#include <lib/core/TLVWriter.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <lib/core/CHIPConfig.h>
#include <lib/core/CHIPEncoding.h>
#include <lib/core/CHIPError.h>
#include <lib/core/TLVBackingStore.h>
#include <lib/core/TLVCommon.h>
#include <lib/core/TLVReader.h>
#include <lib/core/TLVTags.h>
#include <lib/core/TLVTypes.h>
#include <lib/support/BufferWriter.h>
#include <lib/support/CHIPMem.h>
#include <lib/support/CodeUtils.h>
#include <lib/support/SafeInt.h>
#include <lib/support/Span.h>
#include <lib/support/logging/Constants.h>
#include <lib/support/logging/TextOnlyLogging.h>
#include <lib/support/utf8.h>
#include <system/SystemConfig.h>

namespace chip {
namespace TLV {
using namespace chip::Encoding;
TLVWriter::TLVWriter() : ImplicitProfileId(kProfileIdNotSpecified), AppData(nullptr), mBackingStore(nullptr), mBufStart(nullptr), mWritePoint(nullptr), mRemainingLen(0), mLenWritten(0), mMaxLen(0), mReservedSize(0), mContainerType(kTLVType_NotSpecified), mInitializationCookie(0), mContainerOpen(false), mCloseContainerReserved(true)
{
}

void TLVWriter::Init(uint8_t * buf, size_t maxLen)
{
}

CHIP_ERROR TLVWriter::Init(TLVBackingStore & backingStore, uint32_t maxLen /* = UINT32_MAX */)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Finalize()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::ReserveBuffer(uint32_t aBufferSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::PutBoolean(Tag tag, bool v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, uint8_t v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, uint8_t v, bool preserveSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, uint16_t v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, uint16_t v, bool preserveSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, uint32_t v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, uint32_t v, bool preserveSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, uint64_t v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, uint64_t v, bool preserveSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, int8_t v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, int8_t v, bool preserveSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, int16_t v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, int16_t v, bool preserveSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, int32_t v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, int32_t v, bool preserveSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, int64_t v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, int64_t v, bool preserveSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, const float v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, const double v)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::Put(Tag tag, ByteSpan data)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::PutBytes(Tag tag, const uint8_t * buf, uint32_t len)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::PutString(Tag tag, const char * buf)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::PutString(Tag tag, const char * buf, uint32_t len)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::PutString(Tag tag, CharSpan str)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::PutStringF(Tag tag, const char * fmt, ...)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::VPutStringF(Tag tag, const char * fmt, va_list ap)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::PutNull(Tag tag)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::CopyElement(TLVReader & reader)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::CopyElement(Tag tag, TLVReader & reader)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::OpenContainer(Tag tag, TLVType containerType, TLVWriter & containerWriter)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::CloseContainer(TLVWriter & containerWriter)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::StartContainer(Tag tag, TLVType containerType, TLVType & outerContainerType)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::EndContainer(TLVType outerContainerType)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::PutPreEncodedContainer(Tag tag, TLVType containerType, const uint8_t * data, uint32_t dataLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::CopyContainer(TLVReader & container)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::CopyContainer(Tag tag, TLVReader & container)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::CopyContainer(Tag tag, const uint8_t * encodedContainer, uint16_t encodedContainerLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::WriteElementHead(TLVElementType elemType, Tag tag, uint64_t lenOrVal)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::WriteElementWithData(TLVType type, Tag tag, const uint8_t * data, uint32_t dataLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVWriter::WriteData(const uint8_t * p, uint32_t len)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace TLV
} // namespace chip
