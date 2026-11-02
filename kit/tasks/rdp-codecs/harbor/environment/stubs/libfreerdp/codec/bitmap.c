/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * Bitmap Compression
 *
 * Copyright 2004-2012 Jay Sorg <jay.sorg@gmail.com>
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
#include <freerdp/codec/bitmap.h>

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

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
