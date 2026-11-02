/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * Interleaved RLE Bitmap Codec
 *
 * Copyright 2014 Marc-Andre Moreau <marcandre.moreau@gmail.com>
 * Copyright 2015 Thincast Technologies GmbH
 * Copyright 2015 DI (FH) Martin Haimberger <martin.haimberger@thincast.com>
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
#include <freerdp/codec/interleaved.h>
#include <freerdp/log.h>

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

BOOL interleaved_decompress(BITMAP_INTERLEAVED_CONTEXT* WINPR_RESTRICT interleaved,
                            const BYTE* WINPR_RESTRICT pSrcData, UINT32 SrcSize, UINT32 nSrcWidth,
                            UINT32 nSrcHeight, UINT32 bpp, BYTE* WINPR_RESTRICT pDstData,
                            UINT32 DstFormat, UINT32 nDstStep, UINT32 nXDst, UINT32 nYDst,
                            UINT32 nDstWidth, UINT32 nDstHeight,
                            const gdiPalette* WINPR_RESTRICT palette)
{
	WINPR_UNUSED(interleaved);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(nSrcWidth);
	WINPR_UNUSED(nSrcHeight);
	WINPR_UNUSED(bpp);
	WINPR_UNUSED(pDstData);
	WINPR_UNUSED(DstFormat);
	WINPR_UNUSED(nDstStep);
	WINPR_UNUSED(nXDst);
	WINPR_UNUSED(nYDst);
	WINPR_UNUSED(nDstWidth);
	WINPR_UNUSED(nDstHeight);
	WINPR_UNUSED(palette);
	return FALSE;
}

BOOL interleaved_compress(BITMAP_INTERLEAVED_CONTEXT* WINPR_RESTRICT interleaved,
                          BYTE* WINPR_RESTRICT pDstData, UINT32* WINPR_RESTRICT pDstSize,
                          UINT32 nWidth, UINT32 nHeight, const BYTE* WINPR_RESTRICT pSrcData,
                          UINT32 SrcFormat, UINT32 nSrcStep, UINT32 nXSrc, UINT32 nYSrc,
                          const gdiPalette* WINPR_RESTRICT palette, UINT32 bpp)
{
	WINPR_UNUSED(interleaved);
	WINPR_UNUSED(pDstData);
	WINPR_UNUSED(pDstSize);
	WINPR_UNUSED(nWidth);
	WINPR_UNUSED(nHeight);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcFormat);
	WINPR_UNUSED(nSrcStep);
	WINPR_UNUSED(nXSrc);
	WINPR_UNUSED(nYSrc);
	WINPR_UNUSED(palette);
	WINPR_UNUSED(bpp);
	return FALSE;
}

BOOL bitmap_interleaved_context_reset(BITMAP_INTERLEAVED_CONTEXT* WINPR_RESTRICT interleaved)
{
	WINPR_UNUSED(interleaved);
	return FALSE;
}

BITMAP_INTERLEAVED_CONTEXT* bitmap_interleaved_context_new(BOOL Compressor)
{
	WINPR_UNUSED(Compressor);
	return nullptr;
}

void bitmap_interleaved_context_free(BITMAP_INTERLEAVED_CONTEXT* WINPR_RESTRICT interleaved)
{
	WINPR_UNUSED(interleaved);
}
