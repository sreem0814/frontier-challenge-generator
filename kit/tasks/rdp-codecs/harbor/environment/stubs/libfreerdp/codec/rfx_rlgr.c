/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * RemoteFX Codec Library - RLGR
 *
 * Copyright 2011 Vic Lee
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <freerdp/config.h>

#include <winpr/assert.h>

#include "rfx_types.h"
#include "rfx_rlgr.h"

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

int rfx_rlgr_decode(RLGR_MODE mode, const BYTE* WINPR_RESTRICT pSrcData, UINT32 SrcSize,
                    INT16* WINPR_RESTRICT pDstData, UINT32 rDstSize)
{
	WINPR_UNUSED(mode);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(pDstData);
	WINPR_UNUSED(rDstSize);
	return -1;
}

int rfx_rlgr_encode(RLGR_MODE mode, const INT16* WINPR_RESTRICT data, UINT32 data_size,
                    BYTE* WINPR_RESTRICT buffer, UINT32 buffer_size)
{
	WINPR_UNUSED(mode);
	WINPR_UNUSED(data);
	WINPR_UNUSED(data_size);
	WINPR_UNUSED(buffer);
	WINPR_UNUSED(buffer_size);
	return -1;
}
