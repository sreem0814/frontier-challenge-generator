/*
 *
 *    Copyright (c) 2020 Project CHIP Authors
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

#include <lib/core/TLVUtilities.h>
#include <lib/core/CHIPError.h>
#include <lib/core/TLVReader.h>
#include <lib/core/TLVTags.h>
#include <lib/core/TLVTypes.h>
#include <lib/support/CodeUtils.h>

namespace chip {
namespace TLV {
namespace Utilities {
CHIP_ERROR Iterate(const TLVReader & aReader, IterateHandler aHandler, void * aContext)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR Iterate(const TLVReader & aReader, IterateHandler aHandler, void * aContext, const bool aRecurse)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR Count(const TLVReader & aReader, size_t & aCount)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR Count(const TLVReader & aReader, size_t & aCount, const bool aRecurse)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR Find(const TLVReader & aReader, const Tag & aTag, TLVReader & aResult)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR Find(const TLVReader & aReader, const Tag & aTag, TLVReader & aResult, const bool aRecurse)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR Find(const TLVReader & aReader, IterateHandler aPredicate, void * aContext, TLVReader & aResult)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

CHIP_ERROR Find(const TLVReader & aReader, IterateHandler aPredicate, void * aContext, TLVReader & aResult, const bool aRecurse)
{
    return CHIP_ERROR_NOT_IMPLEMENTED;
}

} // namespace Utilities
} // namespace TLV
} // namespace chip
