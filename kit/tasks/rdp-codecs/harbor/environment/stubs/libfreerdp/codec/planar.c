/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * RDP6 Planar Codec
 *
 * Copyright 2013 Marc-Andre Moreau <marcandre.moreau@gmail.com>
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
#include <freerdp/log.h>
#include <freerdp/codec/planar.h>

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

#if !defined(WITHOUT_FREERDP_3x_DEPRECATED)
BOOL planar_decompress(BITMAP_PLANAR_CONTEXT* WINPR_RESTRICT planar,
                       const BYTE* WINPR_RESTRICT pSrcData, UINT32 SrcSize, UINT32 nSrcWidth,
                       UINT32 nSrcHeight, BYTE* WINPR_RESTRICT pDstData, UINT32 DstFormat,
                       UINT32 nDstStep, UINT32 nXDst, UINT32 nYDst, UINT32 nDstWidth,
                       UINT32 nDstHeight, BOOL vFlip)
{
	return freerdp_bitmap_decompress_planar(planar, pSrcData, SrcSize, nSrcWidth, nSrcHeight,
	                                        pDstData, DstFormat, nDstStep, nXDst, nYDst, nDstWidth,
	                                        nDstHeight, vFlip);
}
#endif

BOOL freerdp_bitmap_decompress_planar(BITMAP_PLANAR_CONTEXT* WINPR_RESTRICT planar,
                                      const BYTE* WINPR_RESTRICT pSrcData, UINT32 SrcSize,
                                      UINT32 nSrcWidth, UINT32 nSrcHeight,
                                      BYTE* WINPR_RESTRICT pDstData, UINT32 DstFormat,
                                      UINT32 nDstStep, UINT32 nXDst, UINT32 nYDst, UINT32 nDstWidth,
                                      UINT32 nDstHeight, BOOL vFlip)
{
	WINPR_UNUSED(planar);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(nSrcWidth);
	WINPR_UNUSED(nSrcHeight);
	WINPR_UNUSED(pDstData);
	WINPR_UNUSED(DstFormat);
	WINPR_UNUSED(nDstStep);
	WINPR_UNUSED(nXDst);
	WINPR_UNUSED(nYDst);
	WINPR_UNUSED(nDstWidth);
	WINPR_UNUSED(nDstHeight);
	WINPR_UNUSED(vFlip);
	return FALSE;
}

BYTE* freerdp_bitmap_compress_planar(BITMAP_PLANAR_CONTEXT* WINPR_RESTRICT context,
                                     const BYTE* WINPR_RESTRICT data, UINT32 format, UINT32 width,
                                     UINT32 height, UINT32 scanline, BYTE* WINPR_RESTRICT dstData,
                                     UINT32* WINPR_RESTRICT pDstSize)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(data);
	WINPR_UNUSED(format);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	WINPR_UNUSED(scanline);
	WINPR_UNUSED(dstData);
	WINPR_UNUSED(pDstSize);
	return nullptr;
}

BOOL freerdp_bitmap_planar_context_reset(BITMAP_PLANAR_CONTEXT* WINPR_RESTRICT context,
                                         UINT32 width, UINT32 height)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	return FALSE;
}

BITMAP_PLANAR_CONTEXT* freerdp_bitmap_planar_context_new(DWORD flags, UINT32 maxWidth,
                                                         UINT32 maxHeight)
{
	WINPR_UNUSED(flags);
	WINPR_UNUSED(maxWidth);
	WINPR_UNUSED(maxHeight);
	return nullptr;
}

void freerdp_bitmap_planar_context_free(BITMAP_PLANAR_CONTEXT* context)
{
	WINPR_UNUSED(context);
}

void freerdp_planar_switch_bgr(BITMAP_PLANAR_CONTEXT* WINPR_RESTRICT planar, BOOL bgr)
{
	WINPR_UNUSED(planar);
	WINPR_UNUSED(bgr);
}

void freerdp_planar_topdown_image(BITMAP_PLANAR_CONTEXT* WINPR_RESTRICT planar, BOOL topdown)
{
	WINPR_UNUSED(planar);
	WINPR_UNUSED(topdown);
}
