/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * NSCodec Codec
 *
 * Copyright 2011 Samsung, Author Jiten Pathy
 * Copyright 2012 Vic Lee
 * Copyright 2016 Armin Novak <armin.novak@thincast.com>
 * Copyright 2016 Thincast Technologies GmbH
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *	 http://www.apache.org/licenses/LICENSE-2.0
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

BOOL nsc_context_reset(NSC_CONTEXT* WINPR_RESTRICT context, UINT32 width, UINT32 height)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	return FALSE;
}

NSC_CONTEXT* nsc_context_new(void)
{
	return nullptr;
}

void nsc_context_planebuffers_free(NSC_CONTEXT_PRIV* priv)
{
	WINPR_UNUSED(priv);
}

void nsc_context_free(NSC_CONTEXT* context)
{
	WINPR_UNUSED(context);
}

#if defined(WITH_FREERDP_DEPRECATED)
BOOL nsc_context_set_pixel_format(NSC_CONTEXT* context, UINT32 pixel_format)
{
	return nsc_context_set_parameters(context, NSC_COLOR_FORMAT, pixel_format);
}
#endif

BOOL nsc_context_set_parameters(NSC_CONTEXT* WINPR_RESTRICT context, NSC_PARAMETER what,
                                UINT32 value)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(what);
	WINPR_UNUSED(value);
	return FALSE;
}

BOOL nsc_process_message(NSC_CONTEXT* WINPR_RESTRICT context, UINT16 bpp, UINT32 width,
                         UINT32 height, const BYTE* data, UINT32 length,
                         BYTE* WINPR_RESTRICT pDstData, UINT32 DstFormat, UINT32 nDstStride,
                         UINT32 nXDst, UINT32 nYDst, UINT32 nWidth, UINT32 nHeight, UINT32 flip)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(bpp);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	WINPR_UNUSED(data);
	WINPR_UNUSED(length);
	WINPR_UNUSED(pDstData);
	WINPR_UNUSED(DstFormat);
	WINPR_UNUSED(nDstStride);
	WINPR_UNUSED(nXDst);
	WINPR_UNUSED(nYDst);
	WINPR_UNUSED(nWidth);
	WINPR_UNUSED(nHeight);
	WINPR_UNUSED(flip);
	return FALSE;
}
