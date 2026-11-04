/*
 *
 *    Copyright (c) 2024 Project CHIP Authors
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

#include <lib/core/TLVVectorWriter.h>
#include <cstdint>
#include <vector>
#include <lib/core/CHIPError.h>
#include <lib/core/TLVCommon.h>

namespace chip {
namespace TLV {
TlvVectorWriter::TlvVectorWriter(std::vector<uint8_t> & buffer) : mVectorBuffer(buffer)
{
}

TlvVectorWriter::~TlvVectorWriter() = default;

TlvVectorWriter::TlvVectorBuffer::TlvVectorBuffer(std::vector<uint8_t> & buffer) : mFinalBuffer(buffer)
{
}

TlvVectorWriter::TlvVectorBuffer::~TlvVectorBuffer()
{
}

CHIP_ERROR TlvVectorWriter::TlvVectorBuffer::OnInit(TLVWriter & /*writer*/, uint8_t *& bufStart, uint32_t & bufLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TlvVectorWriter::TlvVectorBuffer::GetNewBuffer(TLVWriter & /*writer*/, uint8_t *& bufStart, uint32_t & bufLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR TlvVectorWriter::TlvVectorBuffer::FinalizeBuffer(TLVWriter & /*writer*/, uint8_t * bufStart, uint32_t bufLen)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

void TlvVectorWriter::TlvVectorBuffer::ResizeWriteBuffer(uint8_t *& bufStart, uint32_t & bufLen)
{
}

} // namespace TLV
} // namespace chip
