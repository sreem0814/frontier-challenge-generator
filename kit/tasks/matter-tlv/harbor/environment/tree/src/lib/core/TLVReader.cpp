/*
 *
 *    Copyright (c) 2020-2023 Project CHIP Authors
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

#include <lib/core/TLVReader.h>
#include <stdint.h>
#include <string.h>
#include <lib/core/CHIPConfig.h>
#include <lib/core/CHIPEncoding.h>
#include <lib/core/CHIPError.h>
#include <lib/core/CHIPSafeCasts.h>
#include <lib/core/DataModelTypes.h>
#include <lib/core/Optional.h>
#include <lib/core/TLVBackingStore.h>
#include <lib/core/TLVCommon.h>
#include <lib/core/TLVTags.h>
#include <lib/core/TLVTypes.h>
#include <lib/support/BufferWriter.h>
#include <lib/support/BytesToHex.h>
#include <lib/support/CHIPMem.h>
#include <lib/support/CodeUtils.h>
#include <lib/support/SafeInt.h>
#include <lib/support/Span.h>
#include <lib/support/logging/TextOnlyLogging.h>
#include <lib/support/utf8.h>

namespace chip {
namespace TLV {
using namespace chip::Encoding;
TLVReader::TLVReader() : ImplicitProfileId(kProfileIdNotSpecified), AppData(nullptr), mElemLenOrVal(0), mBackingStore(nullptr), mReadPoint(nullptr), mBufEnd(nullptr), mLenRead(0), mMaxLen(0), mContainerType(kTLVType_NotSpecified), mControlByte(kTLVControlByte_NotSpecified), mContainerOpen(false)
{
}

void TLVReader::Init(const uint8_t * data, size_t dataLen)
{
}

CHIP_ERROR TLVReader::Init(TLVBackingStore & backingStore, uint32_t maxLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

void TLVReader::Init(const TLVReader & aReader)
{
}

TLVType TLVReader::GetType() const
{
    return kTLVType_NotSpecified;
}

uint32_t TLVReader::GetLength() const
{
    return 0;
}

CHIP_ERROR TLVReader::Get(bool & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(int8_t & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(int16_t & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(int32_t & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(int64_t & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(uint8_t & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(uint16_t & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(uint32_t & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(uint64_t & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(float & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(double & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(ByteSpan & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(CharSpan & v) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Get(Optional<LocalizedStringIdentifier> & lsid)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::GetLocalizedStringIdentifierImpl(Optional<LocalizedStringIdentifier> & lsid, bool validateCharString)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::GetBytes(uint8_t * buf, size_t bufSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::GetString(char * buf, size_t bufSize)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::DupBytes(uint8_t *& buf, uint32_t & dataLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::DupString(char *& buf)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::GetDataPtr(const uint8_t *& data) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::OpenContainer(TLVReader & containerReader)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::CloseContainer(TLVReader & containerReader)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::EnterContainer(TLVType & outerContainerType)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::ExitContainer(TLVType outerContainerType)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::VerifyEndOfContainer()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Next()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Expect(Tag expectedTag)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Next(Tag expectedTag)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Expect(TLVType expectedType, Tag expectedTag)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Next(TLVType expectedType, Tag expectedTag)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::Skip()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

void TLVReader::ClearElementState()
{
}

CHIP_ERROR TLVReader::SkipData()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::SkipToEndOfContainer()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::ReadElement()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::VerifyElement()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

Tag TLVReader::ReadTag(TLVTagControl tagControl, const uint8_t *& p) const
{
    return {};
}

CHIP_ERROR TLVReader::ReadData(uint8_t * buf, uint32_t len)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::EnsureData(CHIP_ERROR noDataErr)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::GetElementHeadLength(uint8_t & elemHeadBytes) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

TLVElementType TLVReader::ElementType() const
{
    return TLVElementType::NotSpecified;
}

CHIP_ERROR TLVReader::FindElementWithTag(Tag tag, TLVReader & destReader) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVReader::CountRemainingInContainer(size_t * size) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR ContiguousBufferTLVReader::OpenContainer(ContiguousBufferTLVReader & containerReader)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR ContiguousBufferTLVReader::GetStringView(Span<const char> & data)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR ContiguousBufferTLVReader::GetByteView(ByteSpan & data)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace TLV
} // namespace chip
