/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * ClearCodec Bitmap Compression
 *
 * Copyright 2014 Marc-Andre Moreau <marcandre.moreau@gmail.com>
 * Copyright 2016 Armin Novak <armin.novak@thincast.com>
 * Copyright 2016 Thincast Technologies GmbH
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
#include <freerdp/codec/color.h>
#include <freerdp/codec/clear.h>

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

#if !defined(WITHOUT_FREERDP_3x_DEPRECATED)
int clear_compress(CLEAR_CONTEXT* WINPR_RESTRICT clear, const BYTE* WINPR_RESTRICT pSrcData,
                   UINT32 SrcSize, BYTE** WINPR_RESTRICT ppDstData, UINT32* WINPR_RESTRICT pDstSize)
{
	WINPR_UNUSED(clear);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(ppDstData);
	WINPR_UNUSED(pDstSize);
	return -1;
}
#endif

INT32 clear_decompress(CLEAR_CONTEXT* WINPR_RESTRICT clear, const BYTE* WINPR_RESTRICT pSrcData,
                       UINT32 SrcSize, UINT32 nWidth, UINT32 nHeight, BYTE* WINPR_RESTRICT pDstData,
                       UINT32 DstFormat, UINT32 nDstStep, UINT32 nXDst, UINT32 nYDst,
                       UINT32 nDstWidth, UINT32 nDstHeight,
                       const gdiPalette* WINPR_RESTRICT palette)
{
	WINPR_UNUSED(clear);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(nWidth);
	WINPR_UNUSED(nHeight);
	WINPR_UNUSED(pDstData);
	WINPR_UNUSED(DstFormat);
	WINPR_UNUSED(nDstStep);
	WINPR_UNUSED(nXDst);
	WINPR_UNUSED(nYDst);
	WINPR_UNUSED(nDstWidth);
	WINPR_UNUSED(nDstHeight);
	WINPR_UNUSED(palette);
	return -1;
}

BOOL clear_context_reset(CLEAR_CONTEXT* WINPR_RESTRICT clear)
{
	WINPR_UNUSED(clear);
	return FALSE;
}

CLEAR_CONTEXT* clear_context_new(BOOL Compressor)
{
	WINPR_UNUSED(Compressor);
	return nullptr;
}

void clear_context_free(CLEAR_CONTEXT* WINPR_RESTRICT clear)
{
	WINPR_UNUSED(clear);
}
