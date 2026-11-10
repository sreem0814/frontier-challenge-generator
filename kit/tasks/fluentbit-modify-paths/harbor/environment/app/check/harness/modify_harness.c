/*
 * modify_harness.c: drives Fluent Bit's modify filter through its plugin callbacks.
 *
 * Reads cases from stdin, one line per item:
 *   C <id>             start a case
 *   P <key>\t<value>   a filter property (as it would appear in a [FILTER] section)
 *   R <hex>            one record body: a msgpack map, hex encoded
 *   E                  end of case: create the filter, run every record through it as one chunk
 * Writes to stdout, flushed after each case:
 *   C <id> init_fail          the filter instance refused the configuration
 *   C <id> ok <n>             followed by n lines "O <hex>" (the output bodies, in order), then "E"
 *   C <id> error <what>       the filter callback failed in a way that is not a record result
 *
 * The harness links against libfluent-bit.so built from the tree under test. It never interprets
 * the records itself; it only moves msgpack in and out of the filter.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <fluent-bit.h>
#include <fluent-bit/flb_config.h>
#include <fluent-bit/flb_filter.h>
#include <fluent-bit/flb_log_event_encoder.h>
#include <fluent-bit/flb_log_event_decoder.h>
#include <fluent-bit/flb_time.h>
#include <msgpack.h>

#define MAX_PROPS 256
#define MAX_RECS  256

struct prop { char *k; char *v; };

static struct prop props[MAX_PROPS];
static int n_props;
static char *recs[MAX_RECS];
static size_t rec_len[MAX_RECS];
static int n_recs;
static char case_id[256];

static int hexval(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static char *unhex(const char *s, size_t *out_len)
{
    size_t n = strlen(s);
    size_t i;
    char *buf;

    while (n > 0 && (s[n - 1] == '\n' || s[n - 1] == '\r')) n--;
    if (n % 2) return NULL;
    buf = malloc(n / 2 + 1);
    if (!buf) return NULL;
    for (i = 0; i < n / 2; i++) {
        int a = hexval(s[2 * i]), b = hexval(s[2 * i + 1]);
        if (a < 0 || b < 0) { free(buf); return NULL; }
        buf[i] = (char) ((a << 4) | b);
    }
    *out_len = n / 2;
    return buf;
}

static void put_hex(const char *buf, size_t len)
{
    static const char *d = "0123456789abcdef";
    size_t i;
    for (i = 0; i < len; i++) {
        unsigned char c = (unsigned char) buf[i];
        putchar(d[c >> 4]);
        putchar(d[c & 15]);
    }
}

static void reset_case(void)
{
    int i;
    for (i = 0; i < n_props; i++) { free(props[i].k); free(props[i].v); }
    for (i = 0; i < n_recs; i++) free(recs[i]);
    n_props = 0;
    n_recs = 0;
}

static int build_chunk(msgpack_sbuffer *chunk_out, char **buf, size_t *size,
                       struct flb_log_event_encoder *enc)
{
    int i;
    int ret;
    size_t off;
    msgpack_unpacked up;
    struct flb_time tm;

    (void) chunk_out;
    ret = flb_log_event_encoder_init(enc, FLB_LOG_EVENT_FORMAT_DEFAULT);
    if (ret != FLB_EVENT_ENCODER_SUCCESS) return -1;

    for (i = 0; i < n_recs; i++) {
        off = 0;
        msgpack_unpacked_init(&up);
        if (msgpack_unpack_next(&up, recs[i], rec_len[i], &off) != MSGPACK_UNPACK_SUCCESS) {
            msgpack_unpacked_destroy(&up);
            return -1;
        }
        flb_time_set(&tm, 1700000000 + i, 0);
        ret = flb_log_event_encoder_begin_record(enc);
        if (ret == FLB_EVENT_ENCODER_SUCCESS) ret = flb_log_event_encoder_set_timestamp(enc, &tm);
        if (ret == FLB_EVENT_ENCODER_SUCCESS) ret = flb_log_event_encoder_set_body_from_msgpack_object(enc, &up.data);
        if (ret == FLB_EVENT_ENCODER_SUCCESS) ret = flb_log_event_encoder_commit_record(enc);
        msgpack_unpacked_destroy(&up);
        if (ret != FLB_EVENT_ENCODER_SUCCESS) return -1;
    }
    *buf = enc->output_buffer;
    *size = enc->output_length;
    return 0;
}

static void run_case(struct flb_config *config)
{
    int i;
    int ret;
    int count;
    char *in_buf = NULL;
    size_t in_size = 0;
    void *out_buf = NULL;
    size_t out_size = 0;
    const char *res_buf;
    size_t res_size;
    struct flb_filter_instance *ins;
    struct flb_log_event_encoder enc;
    struct flb_log_event_decoder dec;
    struct flb_log_event ev;
    msgpack_sbuffer sb;
    msgpack_packer pk;

    ins = flb_filter_new(config, "modify", NULL);
    if (!ins) {
        printf("C %s error filter_new\n", case_id);
        fflush(stdout);
        return;
    }
    flb_filter_set_property(ins, "match", "*");
    for (i = 0; i < n_props; i++) {
        if (flb_filter_set_property(ins, props[i].k, props[i].v) != 0) {
            printf("C %s init_fail\n", case_id);
            fflush(stdout);
            flb_filter_instance_destroy(ins);
            return;
        }
    }
    ret = flb_filter_init(config, ins);
    if (ret != 0 || ins->context == NULL) {
        printf("C %s init_fail\n", case_id);
        fflush(stdout);
        flb_filter_instance_destroy(ins);
        return;
    }

    memset(&enc, 0, sizeof(enc));
    if (build_chunk(NULL, &in_buf, &in_size, &enc) != 0) {
        printf("C %s error encode\n", case_id);
        fflush(stdout);
        flb_log_event_encoder_destroy(&enc);
        flb_filter_instance_exit(ins, config);
        flb_filter_instance_destroy(ins);
        return;
    }

    ret = ins->p->cb_filter(in_buf, in_size, "test", 4, &out_buf, &out_size,
                            ins, NULL, ins->context, config);
    if (ret == FLB_FILTER_MODIFIED) {
        res_buf = out_buf;
        res_size = out_size;
    }
    else {
        res_buf = in_buf;
        res_size = in_size;
    }

    /* first pass: count the records, second pass: print them */
    count = 0;
    if (flb_log_event_decoder_init(&dec, (char *) res_buf, res_size) == FLB_EVENT_DECODER_SUCCESS) {
        while (flb_log_event_decoder_next(&dec, &ev) == FLB_EVENT_DECODER_SUCCESS) count++;
    }
    flb_log_event_decoder_destroy(&dec);

    printf("C %s ok %d\n", case_id, count);
    if (flb_log_event_decoder_init(&dec, (char *) res_buf, res_size) == FLB_EVENT_DECODER_SUCCESS) {
        while (flb_log_event_decoder_next(&dec, &ev) == FLB_EVENT_DECODER_SUCCESS) {
            msgpack_sbuffer_init(&sb);
            msgpack_packer_init(&pk, &sb, msgpack_sbuffer_write);
            msgpack_pack_object(&pk, *ev.body);
            fputs("O ", stdout);
            put_hex(sb.data, sb.size);
            putchar('\n');
            msgpack_sbuffer_destroy(&sb);
        }
    }
    flb_log_event_decoder_destroy(&dec);
    puts("E");
    fflush(stdout);

    if (ret == FLB_FILTER_MODIFIED && out_buf) {
        flb_free(out_buf);
    }
    flb_log_event_encoder_destroy(&enc);
    flb_filter_instance_exit(ins, config);
    flb_filter_instance_destroy(ins);
}

int main(int argc, char **argv)
{
    char *line = NULL;
    size_t cap = 0;
    ssize_t n;
    char *tab;
    flb_ctx_t *ctx;

    (void) argc;
    (void) argv;

    ctx = flb_create();
    if (!ctx) {
        fprintf(stderr, "flb_create failed\n");
        return 2;
    }
    flb_service_set(ctx, "Log_Level", "error", NULL);

    while ((n = getline(&line, &cap, stdin)) > 0) {
        if (n > 0 && line[n - 1] == '\n') line[--n] = '\0';
        if (line[0] == 'C' && line[1] == ' ') {
            reset_case();
            snprintf(case_id, sizeof(case_id), "%s", line + 2);
        }
        else if (line[0] == 'P' && line[1] == ' ') {
            if (n_props >= MAX_PROPS) continue;
            tab = strchr(line + 2, '\t');
            if (!tab) continue;
            *tab = '\0';
            props[n_props].k = strdup(line + 2);
            props[n_props].v = strdup(tab + 1);
            n_props++;
        }
        else if (line[0] == 'R' && line[1] == ' ') {
            if (n_recs >= MAX_RECS) continue;
            recs[n_recs] = unhex(line + 2, &rec_len[n_recs]);
            if (recs[n_recs]) n_recs++;
        }
        else if (line[0] == 'E') {
            run_case(ctx->config);
            reset_case();
        }
    }
    free(line);
    flb_destroy(ctx);
    return 0;
}
