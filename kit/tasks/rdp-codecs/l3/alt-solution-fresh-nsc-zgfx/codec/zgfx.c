/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * ZGFX (RDP8) bulk decompression, written independently from docs/bitmap-codecs.txt section 7.
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
#include <freerdp/codec/zgfx.h>

#define HIST_SIZE 2500000u
#define SEG_MAX 65536u

struct S_ZGFX_CONTEXT
{
	BYTE hist[HIST_SIZE];
	UINT32 pos;
	BYTE out[SEG_MAX];
	UINT32 outLen;
};

typedef struct
{
	UINT8 len;
	UINT16 code;
	UINT8 vbits;
	UINT8 match;
	UINT32 base;
} Tok;

static const Tok TOKENS[] = {
	{ 1, 0x0, 8, 0, 0 },          { 5, 0x11, 5, 1, 0 },         { 5, 0x12, 7, 1, 32 },
	{ 5, 0x13, 9, 1, 160 },       { 5, 0x14, 10, 1, 672 },      { 5, 0x15, 12, 1, 1696 },
	{ 5, 0x18, 0, 0, 0x00 },      { 5, 0x19, 0, 0, 0x01 },      { 6, 0x2C, 14, 1, 5792 },
	{ 6, 0x2D, 15, 1, 22176 },    { 6, 0x34, 0, 0, 0x02 },      { 6, 0x35, 0, 0, 0x03 },
	{ 6, 0x36, 0, 0, 0xFF },      { 7, 0x5C, 18, 1, 54944 },    { 7, 0x5D, 20, 1, 317088 },
	{ 7, 0x6E, 0, 0, 0x04 },      { 7, 0x6F, 0, 0, 0x05 },      { 7, 0x70, 0, 0, 0x06 },
	{ 7, 0x71, 0, 0, 0x07 },      { 7, 0x72, 0, 0, 0x08 },      { 7, 0x73, 0, 0, 0x09 },
	{ 7, 0x74, 0, 0, 0x0A },      { 7, 0x75, 0, 0, 0x0B },      { 7, 0x76, 0, 0, 0x3A },
	{ 7, 0x77, 0, 0, 0x3B },      { 7, 0x78, 0, 0, 0x3C },      { 7, 0x79, 0, 0, 0x3D },
	{ 7, 0x7A, 0, 0, 0x3E },      { 7, 0x7B, 0, 0, 0x3F },      { 7, 0x7C, 0, 0, 0x40 },
	{ 7, 0x7D, 0, 0, 0x80 },      { 8, 0xBC, 20, 1, 1365664 },  { 8, 0xBD, 21, 1, 2414240 },
	{ 8, 0xFC, 0, 0, 0x0C },      { 8, 0xFD, 0, 0, 0x38 },      { 8, 0xFE, 0, 0, 0x39 },
	{ 8, 0xFF, 0, 0, 0x66 },      { 9, 0x17C, 22, 1, 4511392 }, { 9, 0x17D, 23, 1, 8705696 },
	{ 9, 0x17E, 24, 1, 17094304 },
};

typedef struct
{
	const BYTE* data;
	size_t nbits;
	size_t pos;
} Bits;

static int get_bits(Bits* b, unsigned n, UINT32* v)
{
	UINT32 r = 0;
	if (b->pos + n > b->nbits)
		return 0;
	for (unsigned i = 0; i < n; i++, b->pos++)
		r = (r << 1) | ((b->data[b->pos >> 3] >> (7 - (b->pos & 7))) & 1);
	*v = r;
	return 1;
}

static int emit(ZGFX_CONTEXT* z, BYTE c)
{
	if (z->outLen >= SEG_MAX)
		return 0;
	z->out[z->outLen++] = c;
	z->hist[z->pos] = c;
	z->pos = (z->pos + 1) % HIST_SIZE;
	return 1;
}

static int segment(ZGFX_CONTEXT* z, const BYTE* p, size_t n)
{
	z->outLen = 0;
	if (n < 2)
		return 0;
	const BYTE hdr = p[0];
	const BYTE* d = p + 1;
	const size_t dn = n - 1;
	if (!(hdr & 0x20))
	{
		if (dn > SEG_MAX)
			return 0;
		for (size_t i = 0; i < dn; i++)
			(void)emit(z, d[i]);
		return 1;
	}
	const size_t total = 8 * (dn - 1);
	if (total < d[dn - 1])
		return 0;
	Bits b = { d, total - d[dn - 1], 0 };
	while (b.pos < b.nbits)
	{
		UINT32 code = 0;
		unsigned have = 0;
		size_t t = 0;
		for (; t < ARRAYSIZE(TOKENS); t++)
		{
			while (have < TOKENS[t].len)
			{
				UINT32 bit = 0;
				if (!get_bits(&b, 1, &bit))
					return 0;
				code = (code << 1) | bit;
				have++;
			}
			if (code == TOKENS[t].code)
				break;
		}
		if (t == ARRAYSIZE(TOKENS))
			return 0;
		UINT32 v = 0;
		if (!get_bits(&b, TOKENS[t].vbits, &v))
			return 0;
		v += TOKENS[t].base;
		if (!TOKENS[t].match)
		{
			if (!emit(z, (BYTE)v))
				return 0;
			continue;
		}
		if (v == 0)
		{
			UINT32 count = 0;
			if (!get_bits(&b, 15, &count))
				return 0;
			b.pos = (b.pos + 7) & ~(size_t)7;
			if (b.pos / 8 + count > dn - 1)
				return 0;
			for (UINT32 i = 0; i < count; i++)
				if (!emit(z, d[b.pos / 8 + i]))
					return 0;
			b.pos += 8ull * count;
			continue;
		}
		UINT32 bit = 0;
		UINT32 len = 3;
		if (!get_bits(&b, 1, &bit))
			return 0;
		if (bit)
		{
			unsigned extra = 2;
			len = 4;
			for (;;)
			{
				if (!get_bits(&b, 1, &bit))
					return 0;
				if (!bit)
					break;
				len *= 2;
				extra++;
			}
			UINT32 add = 0;
			if (!get_bits(&b, extra, &add))
				return 0;
			len += add;
		}
		UINT32 src = (z->pos + HIST_SIZE - (v % HIST_SIZE)) % HIST_SIZE;
		for (UINT32 i = 0; i < len; i++)
		{
			if (!emit(z, z->hist[src]))
				return 0;
			src = (src + 1) % HIST_SIZE;
		}
	}
	return 1;
}

static UINT32 le32(const BYTE* p)
{
	return p[0] | ((UINT32)p[1] << 8) | ((UINT32)p[2] << 16) | ((UINT32)p[3] << 24);
}

int zgfx_decompress(ZGFX_CONTEXT* WINPR_RESTRICT zgfx, const BYTE* WINPR_RESTRICT pSrcData,
                    UINT32 SrcSize, BYTE** WINPR_RESTRICT ppDstData,
                    UINT32* WINPR_RESTRICT pDstSize, UINT32 flags)
{
	WINPR_UNUSED(flags);
	if (!zgfx || !ppDstData || !pDstSize)
		return -1;
	*ppDstData = nullptr;
	*pDstSize = 0;
	if (!pSrcData || SrcSize < 1)
		return -1;
	if (pSrcData[0] == 0xE0)
	{
		if (!segment(zgfx, pSrcData + 1, SrcSize - 1))
			return -1;
		if (zgfx->outLen)
		{
			BYTE* o = malloc(zgfx->outLen);
			if (!o)
				return -1;
			memcpy(o, zgfx->out, zgfx->outLen);
			*ppDstData = o;
			*pDstSize = zgfx->outLen;
		}
		return 1;
	}
	if (pSrcData[0] != 0xE1 || SrcSize < 7)
		return -1;
	const UINT32 count = pSrcData[1] | ((UINT32)pSrcData[2] << 8);
	const UINT32 size = le32(pSrcData + 3);
	size_t off = 7;
	size_t used = 0;
	BYTE* o = malloc(size ? size : 1);
	if (!o)
		return -1;
	for (UINT32 i = 0; i < count; i++)
	{
		if (off + 4 > SrcSize)
			goto fail;
		const UINT32 sl = le32(pSrcData + off);
		off += 4;
		if (sl > SrcSize - off)
			goto fail;
		if (!segment(zgfx, pSrcData + off, sl))
			goto fail;
		off += sl;
		if (used + zgfx->outLen > size)
			goto fail;
		memcpy(o + used, zgfx->out, zgfx->outLen);
		used += zgfx->outLen;
	}
	if (used != size)
		goto fail;
	*ppDstData = o;
	*pDstSize = size;
	return 1;
fail:
	free(o);
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
	WINPR_UNUSED(ppDstData);
	WINPR_UNUSED(pDstSize);
	WINPR_UNUSED(pFlags);
	return -1;
}

void zgfx_context_reset(ZGFX_CONTEXT* WINPR_RESTRICT zgfx, BOOL flush)
{
	if (zgfx && flush)
	{
		memset(zgfx->hist, 0, sizeof(zgfx->hist));
		zgfx->pos = 0;
	}
}

ZGFX_CONTEXT* zgfx_context_new(BOOL Compressor)
{
	WINPR_UNUSED(Compressor);
	return calloc(1, sizeof(ZGFX_CONTEXT));
}

void zgfx_context_free(ZGFX_CONTEXT* zgfx)
{
	free(zgfx);
}
