/*
 * codec_runner: feeds recorded bitmap-codec streams to the FreeRDP decoder entry points and prints one
 * result line per decode call.
 *
 *   codec_runner <cases.bin> [--dump DIR] [--timeout SECONDS]
 *
 * cases.bin is a sequence of records (little endian):
 *   "SEQ1" u32 seq_id, u8 codec, u8[3] reserved,
 *   u32 dst_w, dst_h, dst_format, dst_stride, fill_seed, ctx0, ctx1, nsteps
 *   then nsteps x { u32 step_id, u32 param[8], u32 palette_format (0 = none),
 *                   [u32 palette[256] if palette_format != 0], u32 data_len, data }
 * codec: 1 interleaved, 2 planar, 3 nsc, 4 rfx, 5 progressive, 6 clear, 7 zgfx (bulk data: the step's
 * output bytes, not a destination image, are what gets hashed and dumped).
 *
 * Every sequence runs in its own child process with one fresh codec context; its steps are decoded in
 * order into one destination buffer (dst_stride * dst_h bytes, pre-filled from fill_seed). After each
 * step the child prints "R <seq> <step> <ok> <hash> <logged>", where ok is 1 when the call reported
 * success, hash is the FNV-1a 64 hash of the whole destination buffer, and logged is 1 when the
 * library wrote anything to stdout/stderr during the call. A child that crashes or times out gets a
 * line "X <seq> <reason>"; its remaining steps count as failed.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <freerdp/codec/color.h>
#include <freerdp/codec/interleaved.h>
#include <freerdp/codec/planar.h>
#include <freerdp/codec/nsc.h>
#include <freerdp/codec/rfx.h>
#include <freerdp/codec/progressive.h>
#include <freerdp/codec/clear.h>
#include <freerdp/codec/zgfx.h>
#include <freerdp/codec/region.h>

typedef struct
{
	uint32_t step_id;
	uint32_t param[8];
	uint32_t palette_format;
	uint32_t palette[256];
	uint32_t len;
	const uint8_t* data;
} Step;

typedef struct
{
	uint32_t seq_id;
	uint8_t codec;
	uint32_t dst_w, dst_h, dst_format, dst_stride, fill_seed, ctx0, ctx1, nsteps;
	Step* steps;
} Seq;

static const uint8_t* g_buf;
static size_t g_len;
static size_t g_pos;
static int g_out = 1;
static const char* g_dump;

static int rd32(uint32_t* v)
{
	if (g_pos + 4 > g_len)
		return 0;
	*v = (uint32_t)g_buf[g_pos] | ((uint32_t)g_buf[g_pos + 1] << 8) |
	     ((uint32_t)g_buf[g_pos + 2] << 16) | ((uint32_t)g_buf[g_pos + 3] << 24);
	g_pos += 4;
	return 1;
}

static int read_seq(Seq* s)
{
	uint32_t magic = 0, w = 0;
	memset(s, 0, sizeof(*s));
	if (!rd32(&magic))
		return 0;
	if (magic != 0x31514553u) /* "SEQ1" */
		return -1;
	if (!rd32(&s->seq_id) || !rd32(&w))
		return -1;
	s->codec = (uint8_t)(w & 0xFF);
	if (!rd32(&s->dst_w) || !rd32(&s->dst_h) || !rd32(&s->dst_format) || !rd32(&s->dst_stride) ||
	    !rd32(&s->fill_seed) || !rd32(&s->ctx0) || !rd32(&s->ctx1) || !rd32(&s->nsteps))
		return -1;
	if (s->nsteps > 4096)
		return -1;
	s->steps = calloc(s->nsteps ? s->nsteps : 1, sizeof(Step));
	if (!s->steps)
		return -1;
	for (uint32_t i = 0; i < s->nsteps; i++)
	{
		Step* st = &s->steps[i];
		if (!rd32(&st->step_id))
			return -1;
		for (int k = 0; k < 8; k++)
			if (!rd32(&st->param[k]))
				return -1;
		if (!rd32(&st->palette_format))
			return -1;
		if (st->palette_format)
			for (int k = 0; k < 256; k++)
				if (!rd32(&st->palette[k]))
					return -1;
		if (!rd32(&st->len))
			return -1;
		if (g_pos + st->len > g_len)
			return -1;
		st->data = &g_buf[g_pos];
		g_pos += st->len;
	}
	return 1;
}

static uint64_t fnv1a(const uint8_t* p, size_t n)
{
	uint64_t h = 1469598103934665603ULL;
	for (size_t i = 0; i < n; i++)
	{
		h ^= p[i];
		h *= 1099511628211ULL;
	}
	return h;
}

static void fill(uint8_t* dst, size_t n, uint32_t seed, uint32_t format, uint32_t stride, uint32_t h,
                 uint32_t w)
{
	uint64_t x = 0x9E3779B97F4A7C15ULL ^ seed;
	for (size_t i = 0; i < n; i++)
	{
		x ^= x << 13;
		x ^= x >> 7;
		x ^= x << 17;
		dst[i] = (uint8_t)(x >> 24);
	}
	/* opaque destination: the alpha byte of every 32 bpp pixel is 0xFF */
	if (FreeRDPGetBytesPerPixel(format) == 4)
	{
		for (uint32_t y = 0; y < h; y++)
			for (uint32_t c = 0; c < w; c++)
				dst[1ull * y * stride + 4ull * c + 3] = 0xFF;
	}
}

static void emit(const char* line)
{
	size_t n = strlen(line);
	while (n > 0)
	{
		ssize_t r = write(g_out, line, n);
		if (r <= 0)
		{
			if (errno == EINTR)
				continue;
			return;
		}
		line += r;
		n -= (size_t)r;
	}
}

static off_t log_size(void)
{
	struct stat sb;
	if (fstat(2, &sb) != 0)
		return 0;
	return sb.st_size;
}

static void dump(const Seq* s, const Step* st, const uint8_t* dst, size_t n)
{
	char path[4096];
	if (!g_dump)
		return;
	snprintf(path, sizeof(path), "%s/%08" PRIu32 "-%04" PRIu32 ".raw", g_dump, s->seq_id,
	         st->step_id);
	int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (fd < 0)
		return;
	size_t off = 0;
	while (off < n)
	{
		ssize_t r = write(fd, dst + off, n - off);
		if (r <= 0)
			break;
		off += (size_t)r;
	}
	close(fd);
}

static int run_seq(const Seq* s)
{
	const size_t n = 1ull * s->dst_stride * s->dst_h;
	uint8_t* dst = malloc(n ? n : 1);
	if (!dst)
		return 2;
	fill(dst, n, s->fill_seed, s->dst_format, s->dst_stride, s->dst_h, s->dst_w);

	BITMAP_INTERLEAVED_CONTEXT* ilv = nullptr;
	BITMAP_PLANAR_CONTEXT* planar = nullptr;
	NSC_CONTEXT* nsc = nullptr;
	RFX_CONTEXT* rfx = nullptr;
	PROGRESSIVE_CONTEXT* prog = nullptr;
	CLEAR_CONTEXT* clear = nullptr;
	ZGFX_CONTEXT* zgfx = nullptr;
	int ctx_ok = 0;

	switch (s->codec)
	{
		case 1:
			ilv = bitmap_interleaved_context_new(FALSE);
			ctx_ok = ilv != nullptr;
			break;
		case 2:
			planar = freerdp_bitmap_planar_context_new(0, s->ctx0, s->ctx1);
			ctx_ok = planar != nullptr;
			break;
		case 3:
			nsc = nsc_context_new();
			ctx_ok = nsc != nullptr;
			break;
		case 4:
			rfx = rfx_context_new(FALSE);
			if (rfx)
			{
				rfx_context_set_pixel_format(rfx, s->ctx0);
				ctx_ok = rfx_context_reset(rfx, s->dst_w, s->dst_h) ? 1 : 0;
			}
			break;
		case 5:
			prog = progressive_context_new(FALSE);
			if (prog)
				ctx_ok = progressive_create_surface_context(prog, (UINT16)s->ctx0, s->dst_w,
				                                            s->dst_h) >= 0;
			break;
		case 6:
			clear = clear_context_new(FALSE);
			ctx_ok = clear != nullptr;
			break;
		case 7:
			zgfx = zgfx_context_new(FALSE);
			ctx_ok = zgfx != nullptr;
			break;
		default:
			break;
	}

	for (uint32_t i = 0; i < s->nsteps; i++)
	{
		const Step* st = &s->steps[i];
		const uint32_t* p = st->param;
		int ok = 0;
		BYTE* out = nullptr;
		UINT32 outSize = 0;
		const off_t before = log_size();
		/* the decoder gets an exact-size private copy of the stream */
		uint8_t* src = malloc(st->len ? st->len : 1);
		if (src)
			memcpy(src, st->data, st->len);

		if (ctx_ok && src)
		{
			switch (s->codec)
			{
				case 1:
				{
					gdiPalette pal;
					memset(&pal, 0, sizeof(pal));
					pal.format = st->palette_format;
					memcpy(pal.palette, st->palette, sizeof(pal.palette));
					ok = interleaved_decompress(ilv, src, st->len, p[0], p[1], p[2], dst,
					                            s->dst_format, s->dst_stride, p[3], p[4], p[5], p[6],
					                            st->palette_format ? &pal : nullptr)
					         ? 1
					         : 0;
					break;
				}
				case 2:
					ok = freerdp_bitmap_decompress_planar(planar, src, st->len, p[0], p[1], dst,
					                                      s->dst_format, s->dst_stride, p[2], p[3],
					                                      p[4], p[5], p[6] ? TRUE : FALSE)
					         ? 1
					         : 0;
					break;
				case 3:
					ok = nsc_process_message(nsc, 32, p[0], p[1], src, st->len, dst, s->dst_format,
					                         s->dst_stride, p[2], p[3], s->dst_w, s->dst_h, p[4])
					         ? 1
					         : 0;
					break;
				case 4:
				{
					REGION16 region;
					region16_init(&region);
					ok = rfx_process_message(rfx, src, st->len, p[0], p[1], dst, s->dst_format,
					                         s->dst_stride, s->dst_h, &region)
					         ? 1
					         : 0;
					region16_uninit(&region);
					break;
				}
				case 5:
				{
					REGION16 region;
					region16_init(&region);
					ok = progressive_decompress(prog, src, st->len, dst, s->dst_format,
					                            s->dst_stride, 0, 0, &region, (UINT16)s->ctx0,
					                            p[0]) >= 0
					         ? 1
					         : 0;
					region16_uninit(&region);
					break;
				}
				case 6:
					ok = clear_decompress(clear, src, st->len, p[0], p[1], dst, s->dst_format,
					                      s->dst_stride, p[2], p[3], s->dst_w, s->dst_h,
					                      nullptr) >= 0
					         ? 1
					         : 0;
					break;
				case 7:
					ok = zgfx_decompress(zgfx, src, st->len, &out, &outSize, 0) >= 0 ? 1 : 0;
					break;
				default:
					break;
			}
		}
		free(src);
		fflush(stdout);
		fflush(stderr);
		const int logged = log_size() != before;
		const uint8_t* hb = dst;
		size_t hn = n;
		if (s->codec == 7)
		{
			hb = out ? out : (const uint8_t*)"";
			hn = out ? outSize : 0;
		}
		char line[160];
		snprintf(line, sizeof(line), "R %" PRIu32 " %" PRIu32 " %d %016" PRIx64 " %d\n", s->seq_id,
		         st->step_id, ok, fnv1a(hb, hn), logged);
		emit(line);
		if (ok)
			dump(s, st, hb, hn);
		free(out);
	}

	bitmap_interleaved_context_free(ilv);
	freerdp_bitmap_planar_context_free(planar);
	nsc_context_free(nsc);
	rfx_context_free(rfx);
	progressive_context_free(prog);
	clear_context_free(clear);
	zgfx_context_free(zgfx);
	free(dst);
	return 0;
}

int main(int argc, char** argv)
{
	unsigned timeout = 20;
	const char* logdir = nullptr;
	if (argc < 2)
	{
		fprintf(stderr, "usage: %s cases.bin [--dump DIR] [--timeout S] [--logdir DIR]\n", argv[0]);
		return 2;
	}
	for (int i = 2; i < argc; i++)
	{
		if (!strcmp(argv[i], "--dump") && i + 1 < argc)
			g_dump = argv[++i];
		else if (!strcmp(argv[i], "--timeout") && i + 1 < argc)
			timeout = (unsigned)strtoul(argv[++i], nullptr, 10);
		else if (!strcmp(argv[i], "--logdir") && i + 1 < argc)
			logdir = argv[++i];
	}
	int fd = open(argv[1], O_RDONLY);
	if (fd < 0)
	{
		perror("open");
		return 2;
	}
	struct stat sb;
	if (fstat(fd, &sb) != 0)
		return 2;
	g_len = (size_t)sb.st_size;
	uint8_t* buf = malloc(g_len ? g_len : 1);
	if (!buf)
		return 2;
	size_t got = 0;
	while (got < g_len)
	{
		ssize_t r = read(fd, buf + got, g_len - got);
		if (r <= 0)
			return 2;
		got += (size_t)r;
	}
	close(fd);
	g_buf = buf;

	/* result lines go to a private copy of stdout; the library's own output goes to a log file */
	g_out = dup(1);
	if (g_out < 0)
		return 2;
	char logpath[4096];
	snprintf(logpath, sizeof(logpath), "%s/codec_runner.%d.log", logdir ? logdir : "/tmp",
	         (int)getpid());

	for (;;)
	{
		Seq s;
		const int r = read_seq(&s);
		if (r == 0)
			break;
		if (r < 0)
		{
			fprintf(stderr, "malformed case file at offset %zu\n", g_pos);
			return 2;
		}
		pid_t pid = fork();
		if (pid < 0)
			return 2;
		if (pid == 0)
		{
			int lfd = open(logpath, O_WRONLY | O_CREAT | O_TRUNC, 0600);
			if (lfd >= 0)
			{
				dup2(lfd, 1);
				dup2(lfd, 2);
				close(lfd);
			}
			setvbuf(stdout, nullptr, _IONBF, 0);
			setvbuf(stderr, nullptr, _IONBF, 0);
			alarm(timeout);
			_exit(run_seq(&s));
		}
		int status = 0;
		while (waitpid(pid, &status, 0) < 0 && errno == EINTR)
			;
		if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
		{
			char line[96];
			if (WIFSIGNALED(status))
				snprintf(line, sizeof(line), "X %" PRIu32 " signal%d\n", s.seq_id,
				         WTERMSIG(status));
			else
				snprintf(line, sizeof(line), "X %" PRIu32 " exit%d\n", s.seq_id,
				         WEXITSTATUS(status));
			emit(line);
		}
		free(s.steps);
	}
	unlink(logpath);
	return 0;
}
