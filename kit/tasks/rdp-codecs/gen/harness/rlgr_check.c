/* authoring check: decode RLGR blobs with the pristine rfx_rlgr.c. stdin: records of
   u8 mode, u32 len, bytes; stdout: 4096 int16 per record (binary). */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "rfx_rlgr.h"
int main(void)
{
	for (;;)
	{
		int mode = getchar();
		if (mode == EOF)
			return 0;
		uint32_t len = 0;
		if (fread(&len, 4, 1, stdin) != 1)
			return 1;
		BYTE* buf = malloc(len ? len : 1);
		if (fread(buf, 1, len, stdin) != len)
			return 1;
		INT16 out[4096];
		int rc = rfx_rlgr_decode(mode == 3 ? RLGR3 : RLGR1, buf, len, out, 4096);
		int32_t r = rc;
		fwrite(&r, 4, 1, stdout);
		fwrite(out, 2, 4096, stdout);
		free(buf);
	}
}
