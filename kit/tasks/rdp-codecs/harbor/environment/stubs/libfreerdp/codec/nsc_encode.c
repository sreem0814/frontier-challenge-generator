/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * NSCodec Encoder
 *
 * Copyright 2012 Vic Lee
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

#include <freerdp/codec/nsc.h>
#include <freerdp/codec/color.h>

#include "nsc_types.h"
#include "nsc_encode.h"

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

BOOL nsc_encode(NSC_CONTEXT* WINPR_RESTRICT context, const BYTE* WINPR_RESTRICT bmpdata,
                UINT32 rowstride)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(bmpdata);
	WINPR_UNUSED(rowstride);
	return FALSE;
}

BOOL nsc_compose_message(NSC_CONTEXT* WINPR_RESTRICT context, wStream* WINPR_RESTRICT s,
                         const BYTE* WINPR_RESTRICT bmpdata, UINT32 width, UINT32 height,
                         UINT32 scanline)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(s);
	WINPR_UNUSED(bmpdata);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	WINPR_UNUSED(scanline);
	return FALSE;
}

#if !defined(WITHOUT_FREERDP_3x_DEPRECATED)
BOOL nsc_decompose_message(NSC_CONTEXT* WINPR_RESTRICT context, wStream* WINPR_RESTRICT s,
                           BYTE* WINPR_RESTRICT bmpdata, UINT32 x, UINT32 y, UINT32 width,
                           UINT32 height, UINT32 rowstride, UINT32 format, UINT32 flip)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(s);
	WINPR_UNUSED(bmpdata);
	WINPR_UNUSED(x);
	WINPR_UNUSED(y);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	WINPR_UNUSED(rowstride);
	WINPR_UNUSED(format);
	WINPR_UNUSED(flip);
	return FALSE;
}
#endif
