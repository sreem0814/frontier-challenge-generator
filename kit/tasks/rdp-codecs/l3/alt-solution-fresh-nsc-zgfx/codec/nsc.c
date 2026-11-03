/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * NSCodec decoder, written independently from docs/bitmap-codecs.txt section 3.
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

#include <stdlib.h>
#include <string.h>

#include <winpr/crt.h>
#include <freerdp/codec/nsc.h>
#include <freerdp/codec/color.h>

#include "nsc_types.h"
#include "nsc_encode.h"

static UINT32 rd32(const BYTE* p)
{
	return p[0] | ((UINT32)p[1] << 8) | ((UINT32)p[2] << 16) | ((UINT32)p[3] << 24);
}

/* plane RLE: literals, value value n / value value 0xFF u32, the last 4 bytes raw */
static BOOL rle_plane(const BYTE* in, size_t inLen, BYTE* out, size_t orig)
{
	size_t left = orig;
	size_t i = 0;
	while (left > 4)
	{
		if (i >= inLen)
			return FALSE;
		const BYTE v = in[i++];
		if (left == 5)
		{
			*out++ = v;
			left--;
			continue;
		}
		if (i >= inLen)
			return FALSE;
		if (in[i] != v)
		{
			*out++ = v;
			left--;
			continue;
		}
		i++;
		if (i >= inLen)
			return FALSE;
		size_t n = 0;
		if (in[i] < 0xFF)
			n = (size_t)in[i++] + 2;
		else
		{
			if (inLen - i < 5)
				return FALSE;
			n = rd32(in + i + 1);
			i += 5;
		}
		if (n > left)
			return FALSE;
		memset(out, v, n);
		out += n;
		left -= n;
	}
	if (left < 4 || inLen - i < 4 || i > inLen)
		return FALSE;
	memcpy(out, in + i, 4);
	return TRUE;
}

static BYTE clamp8(int v)
{
	return (BYTE)(v < 0 ? 0 : (v > 255 ? 255 : v));
}

BOOL nsc_process_message(NSC_CONTEXT* WINPR_RESTRICT context, UINT16 bpp, UINT32 width,
                         UINT32 height, const BYTE* data, UINT32 length,
                         BYTE* WINPR_RESTRICT pDstData, UINT32 DstFormat, UINT32 nDstStride,
                         UINT32 nXDst, UINT32 nYDst, UINT32 nWidth, UINT32 nHeight, UINT32 flip)
{
	WINPR_UNUSED(bpp);
	if (!context || !data || !pDstData || nXDst > nWidth || nYDst > nHeight)
		return FALSE;
	const UINT32 minStride = nWidth * FreeRDPGetBytesPerPixel(DstFormat);
	if (nDstStride == 0)
		nDstStride = minStride;
	if (nDstStride < minStride || length < 20)
		return FALSE;
	UINT32 counts[4];
	size_t total = 0;
	for (int k = 0; k < 4; k++)
	{
		counts[k] = rd32(data + 4 * k);
		total += counts[k];
	}
	const BYTE cll = data[16];
	const BYTE cs = data[17];
	if (cll < 1 || cll > 7 || length - 20 < total)
		return FALSE;
	const size_t tw = (width + 7) & ~7u;
	const size_t th = (height + 1) & ~1u;
	size_t orig[4] = { (size_t)width * height, (size_t)width * height, (size_t)width * height,
		               (size_t)width * height };
	if (cs)
	{
		orig[0] = tw * height;
		orig[1] = orig[2] = (tw / 2) * (th / 2);
	}
	BYTE* planes[4] = { 0 };
	BYTE* image = malloc(4ull * width * height + 4);
	BOOL ok = image != nullptr;
	const BYTE* p = data + 20;
	for (int k = 0; ok && k < 4; k++)
	{
		planes[k] = malloc(orig[k] + 8);
		if (!planes[k])
		{
			ok = FALSE;
			break;
		}
		if (counts[k] == 0)
			memset(planes[k], 0xFF, orig[k]);
		else if (counts[k] < orig[k])
			ok = rle_plane(p, counts[k], planes[k], orig[k]);
		else
			memcpy(planes[k], p, orig[k]);
		p += counts[k];
	}
	if (ok)
	{
		const int shift = cll - 1;
		for (size_t y = 0; y < height; y++)
		{
			for (size_t x = 0; x < width; x++)
			{
				const int Y = cs ? planes[0][y * tw + x] : planes[0][y * width + x];
				const size_t ci = cs ? (y >> 1) * (tw / 2) + (x >> 1) : y * width + x;
				const int co = (INT8)(BYTE)(planes[1][ci] << shift);
				const int cg = (INT8)(BYTE)(planes[2][ci] << shift);
				BYTE* px = &image[4 * (y * width + x)];
				px[0] = clamp8(Y - co - cg);
				px[1] = clamp8(Y + cg);
				px[2] = clamp8(Y + co - cg);
				px[3] = planes[3][y * width + x];
			}
		}
		UINT32 cw = width;
		UINT32 ch = height;
		if (1ull * nXDst + width > nWidth)
			cw = nWidth - nXDst;
		if (1ull * nYDst + height > nHeight)
			ch = nHeight - nYDst;
		ok = freerdp_image_copy_no_overlap(pDstData, DstFormat, nDstStride, nXDst, nYDst, cw, ch,
		                                   image, PIXEL_FORMAT_BGRA32, 0, 0, 0, nullptr, flip);
	}
	for (int k = 0; k < 4; k++)
		free(planes[k]);
	free(image);
	return ok;
}

BOOL nsc_context_reset(NSC_CONTEXT* WINPR_RESTRICT context, UINT32 width, UINT32 height)
{
	if (!context || width > UINT16_MAX || height > UINT16_MAX)
		return FALSE;
	context->width = (UINT16)width;
	context->height = (UINT16)height;
	return TRUE;
}

NSC_CONTEXT* nsc_context_new(void)
{
	NSC_CONTEXT* context = calloc(1, sizeof(NSC_CONTEXT));
	if (!context)
		return nullptr;
	context->priv = calloc(1, sizeof(NSC_CONTEXT_PRIV));
	if (!context->priv)
	{
		free(context);
		return nullptr;
	}
	context->priv->log = WLog_Get("com.freerdp.codec.nsc");
	context->ColorLossLevel = 3;
	context->ChromaSubsamplingLevel = 1;
	context->encode = nsc_encode;
	return context;
}

void nsc_context_planebuffers_free(NSC_CONTEXT_PRIV* priv)
{
	if (!priv)
		return;
	for (size_t i = 0; i < ARRAYSIZE(priv->PlaneBuffers); i++)
	{
		winpr_aligned_free(priv->PlaneBuffers[i]);
		priv->PlaneBuffers[i] = nullptr;
	}
	priv->PlaneBuffersLength = 0;
}

void nsc_context_free(NSC_CONTEXT* context)
{
	if (!context)
		return;
	nsc_context_planebuffers_free(context->priv);
	free(context->priv);
	winpr_aligned_free(context->BitmapData);
	free(context);
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
	if (!context)
		return FALSE;
	switch (what)
	{
		case NSC_COLOR_LOSS_LEVEL:
			context->ColorLossLevel = value;
			return TRUE;
		case NSC_ALLOW_SUBSAMPLING:
			context->ChromaSubsamplingLevel = value;
			return TRUE;
		case NSC_DYNAMIC_COLOR_FIDELITY:
			context->DynamicColorFidelity = value != 0;
			return TRUE;
		case NSC_COLOR_FORMAT:
			context->format = value;
			return TRUE;
		default:
			return FALSE;
	}
}
