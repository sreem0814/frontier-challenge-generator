/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * RemoteFX Codec Library - Decode
 *
 * Copyright 2011 Vic Lee
 * Copyright 2011 Norbert Federa <norbert.federa@thincast.com>
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

#include "rfx_types.h"
#include "rfx_decode.h"

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

BOOL rfx_decode_rgb(RFX_CONTEXT* WINPR_RESTRICT context, const RFX_TILE* WINPR_RESTRICT tile,
                    BYTE* WINPR_RESTRICT rgb_buffer, UINT32 stride)
{
	WINPR_UNUSED(context);
	WINPR_UNUSED(tile);
	WINPR_UNUSED(rgb_buffer);
	WINPR_UNUSED(stride);
	return FALSE;
}
