/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * RemoteFX Codec Library
 *
 * Copyright 2011 Vic Lee
 * Copyright 2015 Thincast Technologies GmbH
 * Copyright 2015 Norbert Federa <norbert.federa@thincast.com>
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
#include <freerdp/codec/rfx.h>
#include <freerdp/codec/region.h>

#include "rfx_types.h"

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

RFX_CONTEXT* rfx_context_new(BOOL encoder)
{
	return rfx_context_new_ex(encoder, 0);
}

RFX_CONTEXT* rfx_context_new_ex(BOOL encoder, UINT32 ThreadingFlags)
{
	WINPR_UNUSED(encoder);
	WINPR_UNUSED(ThreadingFlags);
	return nullptr;
}

void rfx_context_free(RFX_CONTEXT* context)
{
	WINPR_UNUSED(context);
}

void rfx_context_set_pixel_format(RFX_CONTEXT* WINPR_RESTRICT context, UINT32 pixel_format)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(pixel_format);
}

UINT32 rfx_context_get_pixel_format(RFX_CONTEXT* WINPR_RESTRICT context)
{
	WINPR_UNUSED(context);
	return 0;
}

void rfx_context_set_palette(RFX_CONTEXT* WINPR_RESTRICT context,
                             const BYTE* WINPR_RESTRICT palette)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(palette);
}

const BYTE* rfx_context_get_palette(RFX_CONTEXT* WINPR_RESTRICT context)
{
	WINPR_UNUSED(context);
	return nullptr;
}

BOOL rfx_context_reset(RFX_CONTEXT* WINPR_RESTRICT context, UINT32 width, UINT32 height)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	return FALSE;
}

BOOL rfx_process_message(RFX_CONTEXT* WINPR_RESTRICT context, const BYTE* WINPR_RESTRICT data,
                         UINT32 length, UINT32 left, UINT32 top, BYTE* WINPR_RESTRICT dst,
                         UINT32 dstFormat, UINT32 dstStride, UINT32 dstHeight,
                         REGION16* WINPR_RESTRICT invalidRegion)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(data);
	WINPR_UNUSED(length);
	WINPR_UNUSED(left);
	WINPR_UNUSED(top);
	WINPR_UNUSED(dst);
	WINPR_UNUSED(dstFormat);
	WINPR_UNUSED(dstStride);
	WINPR_UNUSED(dstHeight);
	WINPR_UNUSED(invalidRegion);
	return FALSE;
}

const UINT32* rfx_message_get_quants(const RFX_MESSAGE* WINPR_RESTRICT message,
                                     UINT16* WINPR_RESTRICT numQuantVals)
{
	WINPR_UNUSED(message);
	if (numQuantVals)
		*numQuantVals = 0;
	return nullptr;
}

const RFX_TILE** rfx_message_get_tiles(const RFX_MESSAGE* WINPR_RESTRICT message,
                                       UINT16* WINPR_RESTRICT numTiles)
{
	WINPR_UNUSED(message);
	if (numTiles)
		*numTiles = 0;
	return nullptr;
}

UINT16 rfx_message_get_tile_count(const RFX_MESSAGE* WINPR_RESTRICT message)
{
	WINPR_UNUSED(message);
	return 0;
}

const RFX_RECT* rfx_message_get_rects(const RFX_MESSAGE* WINPR_RESTRICT message,
                                      UINT16* WINPR_RESTRICT numRects)
{
	WINPR_UNUSED(message);
	if (numRects)
		*numRects = 0;
	return nullptr;
}

UINT16 rfx_message_get_rect_count(const RFX_MESSAGE* WINPR_RESTRICT message)
{
	WINPR_UNUSED(message);
	return 0;
}

void rfx_message_free(RFX_CONTEXT* WINPR_RESTRICT context, RFX_MESSAGE* WINPR_RESTRICT message)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(message);
}

RFX_MESSAGE* rfx_encode_message(RFX_CONTEXT* WINPR_RESTRICT context,
                                const RFX_RECT* WINPR_RESTRICT rects, size_t numRects,
                                const BYTE* WINPR_RESTRICT data, UINT32 w, UINT32 h, size_t s)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(rects);
	WINPR_UNUSED(numRects);
	WINPR_UNUSED(data);
	WINPR_UNUSED(w);
	WINPR_UNUSED(h);
	WINPR_UNUSED(s);
	return nullptr;
}

const RFX_MESSAGE* rfx_message_list_get(const RFX_MESSAGE_LIST* WINPR_RESTRICT messages, size_t idx)
{
	WINPR_UNUSED(messages);
	WINPR_UNUSED(idx);
	return nullptr;
}

void rfx_message_list_free(RFX_MESSAGE_LIST* messages)
{
	WINPR_UNUSED(messages);
}

RFX_MESSAGE_LIST* rfx_encode_messages(RFX_CONTEXT* WINPR_RESTRICT context,
                                      const RFX_RECT* WINPR_RESTRICT rects, size_t numRects,
                                      const BYTE* WINPR_RESTRICT data, UINT32 width, UINT32 height,
                                      UINT32 scanline, size_t* WINPR_RESTRICT numMessages,
                                      size_t maxDataSize)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(rects);
	WINPR_UNUSED(numRects);
	WINPR_UNUSED(data);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	WINPR_UNUSED(scanline);
	WINPR_UNUSED(maxDataSize);
	if (numMessages)
		*numMessages = 0;
	return nullptr;
}

BOOL rfx_write_message(RFX_CONTEXT* WINPR_RESTRICT context, wStream* WINPR_RESTRICT s,
                       const RFX_MESSAGE* WINPR_RESTRICT message)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(s);
	WINPR_UNUSED(message);
	return FALSE;
}

BOOL rfx_compose_message(RFX_CONTEXT* WINPR_RESTRICT context, wStream* WINPR_RESTRICT s,
                         const RFX_RECT* WINPR_RESTRICT rects, size_t numRects,
                         const BYTE* WINPR_RESTRICT data, UINT32 width, UINT32 height,
                         UINT32 scanline)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(s);
	WINPR_UNUSED(rects);
	WINPR_UNUSED(numRects);
	WINPR_UNUSED(data);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	WINPR_UNUSED(scanline);
	return FALSE;
}

BOOL rfx_context_set_mode(RFX_CONTEXT* WINPR_RESTRICT context, RLGR_MODE mode)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(mode);
	return FALSE;
}

RLGR_MODE rfx_context_get_mode(RFX_CONTEXT* WINPR_RESTRICT context)
{
	WINPR_UNUSED(context);
	return RLGR1;
}

UINT32 rfx_context_get_frame_idx(const RFX_CONTEXT* WINPR_RESTRICT context)
{
	WINPR_UNUSED(context);
	return 0;
}

UINT32 rfx_message_get_frame_idx(const RFX_MESSAGE* WINPR_RESTRICT message)
{
	WINPR_UNUSED(message);
	return 0;
}

const char* rfx_get_progressive_block_type_string(UINT16 blockType)
{
	WINPR_UNUSED(blockType);
	return "PROGRESSIVE_WBT_UNKNOWN";
}

BOOL rfx_write_message_progressive_simple(RFX_CONTEXT* WINPR_RESTRICT rfx,
                                          wStream* WINPR_RESTRICT s,
                                          const RFX_MESSAGE* WINPR_RESTRICT msg)
{
	WINPR_UNUSED(rfx);
	WINPR_UNUSED(s);
	WINPR_UNUSED(msg);
	return FALSE;
}
