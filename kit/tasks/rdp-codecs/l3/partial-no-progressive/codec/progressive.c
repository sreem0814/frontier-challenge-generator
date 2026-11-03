/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * Progressive Codec Bitmap Compression
 *
 * Copyright 2014 Marc-Andre Moreau <marcandre.moreau@gmail.com>
 * Copyright 2019 Armin Novak <armin.novak@thincast.com>
 * Copyright 2019 Thincast Technologies GmbH
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
#include <winpr/crt.h>

#include <freerdp/log.h>
#include <freerdp/codec/progressive.h>
#include <freerdp/codec/region.h>

#include "rfx_types.h"
#include "rfx_dwt.h"
#include "progressive.h"

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

INT32 progressive_create_surface_context(PROGRESSIVE_CONTEXT* WINPR_RESTRICT progressive,
                                         UINT16 surfaceId, UINT32 width, UINT32 height)
{
	WINPR_UNUSED(progressive);
	WINPR_UNUSED(surfaceId);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	return -1;
}

int progressive_delete_surface_context(PROGRESSIVE_CONTEXT* WINPR_RESTRICT progressive,
                                       UINT16 surfaceId)
{
	WINPR_UNUSED(progressive);
	WINPR_UNUSED(surfaceId);
	return -1;
}

void rfx_dwt_2d_extrapolate_decode(INT16* WINPR_RESTRICT buffer, INT16* WINPR_RESTRICT dwt_buffer)
{
	WINPR_UNUSED(buffer);
	WINPR_UNUSED(dwt_buffer);
}

INT32 progressive_decompress(PROGRESSIVE_CONTEXT* WINPR_RESTRICT progressive,
                             const BYTE* WINPR_RESTRICT pSrcData, UINT32 SrcSize,
                             BYTE* WINPR_RESTRICT pDstData, UINT32 DstFormat, UINT32 nDstStep,
                             UINT32 nXDst, UINT32 nYDst, REGION16* WINPR_RESTRICT invalidRegion,
                             UINT16 surfaceId, UINT32 frameId)
{
	WINPR_UNUSED(progressive);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(pDstData);
	WINPR_UNUSED(DstFormat);
	WINPR_UNUSED(nDstStep);
	WINPR_UNUSED(nXDst);
	WINPR_UNUSED(nYDst);
	WINPR_UNUSED(invalidRegion);
	WINPR_UNUSED(surfaceId);
	WINPR_UNUSED(frameId);
	return -1;
}

BOOL progressive_rfx_write_message_progressive_simple(
    PROGRESSIVE_CONTEXT* WINPR_RESTRICT progressive, wStream* WINPR_RESTRICT s,
    const RFX_MESSAGE* WINPR_RESTRICT msg)
{
	WINPR_UNUSED(progressive);
	WINPR_UNUSED(s);
	WINPR_UNUSED(msg);
	return FALSE;
}

int progressive_compress(PROGRESSIVE_CONTEXT* WINPR_RESTRICT progressive,
                         const BYTE* WINPR_RESTRICT pSrcData, UINT32 SrcSize, UINT32 SrcFormat,
                         UINT32 Width, UINT32 Height, UINT32 ScanLine,
                         const REGION16* WINPR_RESTRICT invalidRegion,
                         BYTE** WINPR_RESTRICT ppDstData, UINT32* WINPR_RESTRICT pDstSize)
{
	WINPR_UNUSED(progressive);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(SrcFormat);
	WINPR_UNUSED(Width);
	WINPR_UNUSED(Height);
	WINPR_UNUSED(ScanLine);
	WINPR_UNUSED(invalidRegion);
	if (ppDstData)
		*ppDstData = nullptr;
	if (pDstSize)
		*pDstSize = 0;
	return -1;
}

BOOL progressive_context_reset(PROGRESSIVE_CONTEXT* WINPR_RESTRICT progressive)
{
	WINPR_UNUSED(progressive);
	return FALSE;
}

PROGRESSIVE_CONTEXT* progressive_context_new(BOOL Compressor)
{
	return progressive_context_new_ex(Compressor, 0);
}

PROGRESSIVE_CONTEXT* progressive_context_new_ex(BOOL Compressor, UINT32 ThreadingFlags)
{
	WINPR_UNUSED(Compressor);
	WINPR_UNUSED(ThreadingFlags);
	return nullptr;
}

void progressive_context_free(PROGRESSIVE_CONTEXT* progressive)
{
	WINPR_UNUSED(progressive);
}
