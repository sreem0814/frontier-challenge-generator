/*
 *
 *    Copyright (c) 2020-2021 Project CHIP Authors
 *    Copyright (c) 2016-2017 Nest Labs, Inc.
 *    All rights reserved.
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

#include <lib/core/TLVCircularBuffer.h>
#include <lib/core/CHIPError.h>
#include <lib/core/TLVReader.h>
#include <lib/core/TLVTags.h>
#include <lib/core/TLVWriter.h>
#include <lib/support/BufferWriter.h>
#include <lib/support/CodeUtils.h>
#include <stdint.h>

namespace chip {
namespace TLV {
using namespace chip::Encoding;
TLVCircularBuffer::TLVCircularBuffer(uint8_t * inBuffer, uint32_t inBufferLength, uint8_t * inHead)
{
}

TLVCircularBuffer::TLVCircularBuffer(uint8_t * inBuffer, uint32_t inBufferLength)
{
}

void TLVCircularBuffer::Init(uint8_t * inBuffer, uint32_t inBufferLength)
{
}

CHIP_ERROR TLVCircularBuffer::EvictHead()
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVCircularBuffer::OnInit(TLVWriter & writer, uint8_t *& bufStart, uint32_t & bufLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVCircularBuffer::GetNewBuffer(TLVWriter & ioWriter, uint8_t *& outBufStart, uint32_t & outBufLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

void TLVCircularBuffer::GetCurrentWritableBuffer(uint8_t *& outBufStart, uint32_t & outBufLen) const
{
}

CHIP_ERROR TLVCircularBuffer::FinalizeBuffer(TLVWriter & ioWriter, uint8_t * inBufStart, uint32_t inBufLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVCircularBuffer::OnInit(TLVReader & reader, const uint8_t *& bufStart, uint32_t & bufLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TLVCircularBuffer::GetNextBuffer(TLVReader & ioReader, const uint8_t *& outBufStart, uint32_t & outBufLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace TLV
} // namespace chip
