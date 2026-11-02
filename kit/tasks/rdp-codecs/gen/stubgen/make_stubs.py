"""Build the stubbed source tree: pristine FreeRDP 3.32.2 with the bitmap codec implementations removed.

usage: python3 make_stubs.py <pristine tree> <output tree>
Each stubbed file keeps its upstream licence header and gets an empty body: every function the headers
declare is still defined (so the library links and every caller compiles), but it reports failure.
"""
import os
import shutil
import sys

SRC, DST = sys.argv[1], sys.argv[2]
CODEC = "libfreerdp/codec"

NOTE = """
/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */
"""


def header(path):
    with open(os.path.join(SRC, path)) as f:
        lines = f.read().split("\n")
    out = []
    for ln in lines:
        out.append(ln)
        if ln.strip() in ("*/",) or (ln.strip().endswith("*/") and len(out) > 1):
            break
    return "\n".join(out) + "\n"


STUBS = {}

STUBS["interleaved.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>
#include <freerdp/codec/interleaved.h>
#include <freerdp/log.h>
''' + NOTE + r'''
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
'''

STUBS["include/bitmap.h"] = r'''
/* The RLE template that lived here was removed from this source snapshot. */
'''

STUBS["bitmap.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>
#include <freerdp/codec/bitmap.h>
''' + NOTE + r'''
SSIZE_T freerdp_bitmap_compress(const void* WINPR_RESTRICT srcData, UINT32 width, UINT32 height,
                                wStream* WINPR_RESTRICT s, UINT32 bpp, UINT32 byte_limit,
                                UINT32 start_line, wStream* WINPR_RESTRICT temp_s, UINT32 e)
{
	WINPR_UNUSED(srcData);
	WINPR_UNUSED(width);
	WINPR_UNUSED(height);
	WINPR_UNUSED(s);
	WINPR_UNUSED(bpp);
	WINPR_UNUSED(byte_limit);
	WINPR_UNUSED(start_line);
	WINPR_UNUSED(temp_s);
	WINPR_UNUSED(e);
	return -1;
}
'''

STUBS["planar.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>
#include <freerdp/log.h>
#include <freerdp/codec/planar.h>
''' + NOTE + r'''
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
'''

STUBS["nsc.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>
#include <winpr/crt.h>

#include <freerdp/codec/nsc.h>
#include <freerdp/codec/color.h>

#include "nsc_types.h"
#include "nsc_encode.h"
''' + NOTE + r'''
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
'''

STUBS["nsc_encode.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>
#include <winpr/crt.h>

#include <freerdp/codec/nsc.h>
#include <freerdp/codec/color.h>

#include "nsc_types.h"
#include "nsc_encode.h"
''' + NOTE + r'''
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
'''

STUBS["sse/nsc_sse2.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>

#include "../nsc_types.h"
#include "nsc_sse2.h"
''' + NOTE + r'''
void nsc_init_sse2_int(NSC_CONTEXT* WINPR_RESTRICT context)
{
	WINPR_UNUSED(context);
}
'''

STUBS["neon/nsc_neon.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>

#include "../nsc_types.h"
#include "nsc_neon.h"
''' + NOTE + r'''
void nsc_init_neon_int(NSC_CONTEXT* WINPR_RESTRICT context)
{
	WINPR_UNUSED(context);
}
'''

STUBS["sse/rfx_sse2.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>

#include "../rfx_types.h"
#include "rfx_sse2.h"
''' + NOTE + r'''
void rfx_init_sse2_int(RFX_CONTEXT* WINPR_RESTRICT context)
{
	WINPR_UNUSED(context);
}
'''

STUBS["neon/rfx_neon.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>

#include "../rfx_types.h"
#include "rfx_neon.h"
''' + NOTE + r'''
void rfx_init_neon_int(RFX_CONTEXT* WINPR_RESTRICT context)
{
	WINPR_UNUSED(context);
}
'''

STUBS["rfx_decode.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>

#include "rfx_types.h"
#include "rfx_decode.h"
''' + NOTE + r'''
BOOL rfx_decode_rgb(RFX_CONTEXT* WINPR_RESTRICT context, const RFX_TILE* WINPR_RESTRICT tile,
                    BYTE* WINPR_RESTRICT rgb_buffer, UINT32 stride)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(tile);
	WINPR_UNUSED(rgb_buffer);
	WINPR_UNUSED(stride);
	return FALSE;
}
'''

STUBS["rfx_encode.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>

#include "rfx_types.h"
#include "rfx_encode.h"
''' + NOTE + r'''
BOOL rfx_encode_rgb(RFX_CONTEXT* WINPR_RESTRICT context, RFX_TILE* WINPR_RESTRICT tile)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(tile);
	return FALSE;
}
'''

STUBS["rfx_dwt.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>

#include "rfx_dwt.h"
''' + NOTE + r'''
void rfx_dwt_2d_decode(INT16* WINPR_RESTRICT buffer, INT16* WINPR_RESTRICT dwt_buffer)
{
	WINPR_UNUSED(buffer);
	WINPR_UNUSED(dwt_buffer);
}

void rfx_dwt_2d_encode(INT16* WINPR_RESTRICT buffer, INT16* WINPR_RESTRICT dwt_buffer)
{
	WINPR_UNUSED(buffer);
	WINPR_UNUSED(dwt_buffer);
}
'''

STUBS["rfx_quantization.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>

#include "rfx_quantization.h"
''' + NOTE + r'''
BOOL rfx_quantization_decode(INT16* WINPR_RESTRICT buffer,
                             const UINT32* WINPR_RESTRICT quantization_values, size_t nrQuantValues)
{
	WINPR_UNUSED(buffer);
	WINPR_UNUSED(quantization_values);
	WINPR_UNUSED(nrQuantValues);
	return FALSE;
}

BOOL rfx_quantization_encode(INT16* WINPR_RESTRICT buffer,
                             const UINT32* WINPR_RESTRICT quantization_values, size_t nrQuantValues)
{
	WINPR_UNUSED(buffer);
	WINPR_UNUSED(quantization_values);
	WINPR_UNUSED(nrQuantValues);
	return FALSE;
}
'''

STUBS["rfx_rlgr.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>

#include "rfx_types.h"
#include "rfx_rlgr.h"
''' + NOTE + r'''
int rfx_rlgr_decode(RLGR_MODE mode, const BYTE* WINPR_RESTRICT pSrcData, UINT32 SrcSize,
                    INT16* WINPR_RESTRICT pDstData, UINT32 rDstSize)
{
	WINPR_UNUSED(mode);
	WINPR_UNUSED(pSrcData);
	WINPR_UNUSED(SrcSize);
	WINPR_UNUSED(pDstData);
	WINPR_UNUSED(rDstSize);
	return -1;
}

int rfx_rlgr_encode(RLGR_MODE mode, const INT16* WINPR_RESTRICT data, UINT32 data_size,
                    BYTE* WINPR_RESTRICT buffer, UINT32 buffer_size)
{
	WINPR_UNUSED(mode);
	WINPR_UNUSED(data);
	WINPR_UNUSED(data_size);
	WINPR_UNUSED(buffer);
	WINPR_UNUSED(buffer_size);
	return -1;
}
'''

RFX_FUNCS = r'''
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
'''

STUBS["rfx.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>
#include <winpr/crt.h>

#include <freerdp/log.h>
#include <freerdp/codec/rfx.h>
#include <freerdp/codec/region.h>

#include "rfx_types.h"
''' + NOTE + RFX_FUNCS

STUBS["progressive.c"] = r'''
#include <freerdp/config.h>

#include <winpr/assert.h>
#include <winpr/crt.h>

#include <freerdp/log.h>
#include <freerdp/codec/progressive.h>
#include <freerdp/codec/region.h>

#include "rfx_types.h"
#include "rfx_dwt.h"
#include "progressive.h"
''' + NOTE + r'''
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
'''


STUBS["clear.c"] = r"""
#include <freerdp/config.h>

#include <winpr/assert.h>
#include <winpr/crt.h>

#include <freerdp/log.h>
#include <freerdp/codec/color.h>
#include <freerdp/codec/clear.h>
""" + NOTE + r"""
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
"""

STUBS["zgfx.c"] = r"""
#include <freerdp/config.h>

#include <winpr/assert.h>
#include <winpr/crt.h>

#include <freerdp/log.h>
#include <freerdp/codec/zgfx.h>
""" + NOTE + r"""
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
"""

if os.path.exists(DST):
    shutil.rmtree(DST)
shutil.copytree(SRC, DST, symlinks=True)
for rel, body in STUBS.items():
    path = os.path.join(CODEC, rel)
    text = header(path) + "\n" + body.lstrip("\n").rstrip("\n") + "\n"
    if not text.startswith("/*"):
        raise SystemExit("unexpected header in " + path)
    with open(os.path.join(DST, path), "w") as f:
        f.write(text)
print("stubbed", len(STUBS), "files into", DST)
