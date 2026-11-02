/**
 * FreeRDP: A Remote Desktop Protocol Implementation
 * NSCodec Library - SSE2 Optimizations
 *
 * Copyright 2024 Armin Novak <anovak@thincast.com>
 * Copyright 2024 Thincast Technologies GmbH
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

#include "../nsc_types.h"
#include "nsc_neon.h"

/*
 * The implementation in this file was removed from this source snapshot. Every function the codec
 * headers declare is still defined so that the library links, but each one reports failure.
 */

void nsc_init_neon_int(NSC_CONTEXT* WINPR_RESTRICT context)
{
	WINPR_UNUSED(context);
}
