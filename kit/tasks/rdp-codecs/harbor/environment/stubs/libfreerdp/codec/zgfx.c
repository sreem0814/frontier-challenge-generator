/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * ZGFX (RDP8) Bulk Data Compression
 *
 * Copyright 2014 Marc-Andre Moreau <marcandre.moreau@gmail.com>
 * Copyright 2017 Armin Novak <armin.novak@thincast.com>
 * Copyright 2017 Thincast Technologies GmbH
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
#include <freerdp/codec/zgfx.h>

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

int zgfx_decompress(ZGFX_CONTEXT* WINPR_RESTRICT zgfx, const BYTE* WINPR_RESTRICT pSrcData,
                    UINT32 SrcSize, BYTE** WINPR_RESTRICT ppDstData,
                    UINT32* WINPR_RESTRICT pDstSize, UINT32 flags)
{
	WINPR_UNUSED(zgfx);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(flags);
	if (ppDstData)
		*ppDstData = nullptr;
	if (pDstSize)
		*pDstSize = 0;
	return -1;
}

int zgfx_compress_to_stream(ZGFX_CONTEXT* WINPR_RESTRICT zgfx, wStream* WINPR_RESTRICT sDst,
                            const BYTE* WINPR_RESTRICT pUncompressed, UINT32 uncompressedSize,
                            UINT32* WINPR_RESTRICT pFlags)
{
	WINPR_UNUSED(zgfx);
	WINPR_UNUSED(sDst);
	WINPR_UNUSED(pUncompressed);
	WINPR_UNUSED(uncompressedSize);
	WINPR_UNUSED(pFlags);
	return -1;
}

int zgfx_compress(ZGFX_CONTEXT* WINPR_RESTRICT zgfx, const BYTE* WINPR_RESTRICT pSrcData,
                  UINT32 SrcSize, BYTE** WINPR_RESTRICT ppDstData, UINT32* WINPR_RESTRICT pDstSize,
                  UINT32* WINPR_RESTRICT pFlags)
{
	WINPR_UNUSED(zgfx);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(pFlags);
	if (ppDstData)
		*ppDstData = nullptr;
	if (pDstSize)
		*pDstSize = 0;
	return -1;
}

void zgfx_context_reset(ZGFX_CONTEXT* WINPR_RESTRICT zgfx, BOOL flush)
{
	WINPR_UNUSED(zgfx);
	WINPR_UNUSED(flush);
}

ZGFX_CONTEXT* zgfx_context_new(BOOL Compressor)
{
	WINPR_UNUSED(Compressor);
	return nullptr;
}

void zgfx_context_free(ZGFX_CONTEXT* zgfx)
{
	WINPR_UNUSED(zgfx);
}
