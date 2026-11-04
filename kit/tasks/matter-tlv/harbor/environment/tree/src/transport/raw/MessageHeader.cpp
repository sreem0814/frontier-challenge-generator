/*
 *
 *    Copyright (c) 2020-2021 Project CHIP Authors
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

#include "MessageHeader.h"
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <type_traits>
#include <lib/core/CHIPError.h>
#include <lib/support/BufferReader.h>
#include <lib/support/CodeUtils.h>

namespace chip {
uint16_t PacketHeader::EncodeSizeBytes() const
{
    return 0;
}

uint16_t PayloadHeader::EncodeSizeBytes() const
{
    return 0;
}

CHIP_ERROR PacketHeader::DecodeFixedCommon(Encoding::LittleEndian::Reader & reader)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR PacketHeader::DecodeFixed(const System::PacketBufferHandle & buf)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR PacketHeader::Decode(const uint8_t * const data, size_t size, uint16_t * decode_len)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR PacketHeader::DecodeAndConsume(const System::PacketBufferHandle & buf)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR PayloadHeader::Decode(const uint8_t * const data, size_t size, uint16_t * decode_len)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR PayloadHeader::DecodeAndConsume(const System::PacketBufferHandle & buf)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR PacketHeader::Encode(uint8_t * data, size_t size, uint16_t * encode_size) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR PacketHeader::EncodeBeforeData(const System::PacketBufferHandle & buf) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR PayloadHeader::Encode(uint8_t * data, size_t size, uint16_t * encode_size) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR PayloadHeader::EncodeBeforeData(const System::PacketBufferHandle & buf) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR MessageAuthenticationCode::Decode(const PacketHeader & packetHeader, const uint8_t * const data, size_t size, uint16_t * decode_len)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR MessageAuthenticationCode::Encode(const PacketHeader & packetHeader, uint8_t * data, size_t size, uint16_t * encode_size) const
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace chip
