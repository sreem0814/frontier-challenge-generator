/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * RemoteFX Codec Library - Quantization
 *
 * Copyright 2011 Vic Lee
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

#include "rfx_quantization.h"

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

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
