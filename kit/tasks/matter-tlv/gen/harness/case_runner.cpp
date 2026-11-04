// case_runner: drives libchipcore.a through case scripts and prints one transcript per case.
//
//   case_runner <cases.txt> [--timeout S] [--only ID]
//
// A case file holds blocks:
//   CASE <id> <bucket>
//   <op> <args...>          one operation per line (see the dispatch in RunOp)
//   END
// Every case runs in its own forked process with a time and memory limit. For each case the runner prints
//   C <id> <bucket> <nbytes>\n<transcript>
// or, when the case process crashed or timed out,
//   X <id> <bucket> <reason>
// The transcript records each operation's CHIP_ERROR (as a hex integer) and every value it produced.
#include <lib/core/CHIPError.h>
#include <lib/core/TLV.h>
#include <lib/core/TLVCircularBuffer.h>
#include <lib/core/TLVDebug.h>
#include <lib/core/TLVUpdater.h>
#include <lib/core/TLVUtilities.h>
#include <lib/core/TLVVectorWriter.h>
#include <lib/support/CHIPMem.h>
#include <lib/support/jsontlv/JsonToTlv.h>
#include <lib/support/jsontlv/TextFormat.h>
#include <lib/support/jsontlv/TlvJson.h>
#include <lib/support/jsontlv/TlvToJson.h>
#include <setup_payload/AdditionalDataPayloadParser.h>
#include <setup_payload/Base38Decode.h>
#include <setup_payload/Base38Encode.h>
#include <setup_payload/ManualSetupPayloadGenerator.h>
#include <setup_payload/ManualSetupPayloadParser.h>
#include <setup_payload/QRCodeSetupPayloadGenerator.h>
#include <setup_payload/QRCodeSetupPayloadParser.h>
#include <setup_payload/SetupPayload.h>
#include <transport/raw/MessageHeader.h>

#include <cinttypes>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include <fcntl.h>
#include <signal.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

using namespace chip;
using namespace chip::TLV;

namespace {

std::string gOut;

void P(const char * fmt, ...) __attribute__((format(printf, 1, 2)));
void P(const char * fmt, ...)
{
    char tmp[4096];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(tmp, sizeof tmp, fmt, ap);
    va_end(ap);
    if (n < 0)
        return;
    if (static_cast<size_t>(n) < sizeof tmp)
    {
        gOut.append(tmp, static_cast<size_t>(n));
        return;
    }
    std::vector<char> big(static_cast<size_t>(n) + 1);
    va_start(ap, fmt);
    vsnprintf(big.data(), big.size(), fmt, ap);
    va_end(ap);
    gOut.append(big.data(), static_cast<size_t>(n));
}

void PErr(CHIP_ERROR e) { P(" e=%" PRIx32, e.AsInteger()); }

void PHex(const uint8_t * p, size_t n)
{
    static const char * d = "0123456789abcdef";
    if (n == 0)
    {
        gOut += '-';
        return;
    }
    for (size_t i = 0; i < n; i++)
    {
        gOut += d[p[i] >> 4];
        gOut += d[p[i] & 15];
    }
}

// Text with anything outside printable ASCII escaped, so transcripts stay one token per value.
void PText(const char * p, size_t n)
{
    gOut += '"';
    for (size_t i = 0; i < n; i++)
    {
        unsigned char c = static_cast<unsigned char>(p[i]);
        if (c == '\\' || c == '"')
        {
            gOut += '\\';
            gOut += static_cast<char>(c);
        }
        else if (c == '\n')
            gOut += "\\n";
        else if (c >= 0x20 && c < 0x7f)
            gOut += static_cast<char>(c);
        else
        {
            char b[8];
            snprintf(b, sizeof b, "\\x%02x", c);
            gOut += b;
        }
    }
    gOut += '"';
}

std::vector<uint8_t> Hex(const std::string & s)
{
    std::vector<uint8_t> v;
    if (s == "-")
        return v;
    for (size_t i = 0; i + 1 < s.size(); i += 2)
        v.push_back(static_cast<uint8_t>(strtoul(s.substr(i, 2).c_str(), nullptr, 16)));
    return v;
}

std::string HexStr(const std::string & s)
{
    std::vector<uint8_t> v = Hex(s);
    return std::string(v.begin(), v.end());
}

uint64_t U(const std::string & s) { return strtoull(s.c_str(), nullptr, 0); }
int64_t I(const std::string & s) { return strtoll(s.c_str(), nullptr, 0); }

// Tags: a = anonymous, cN = context, mN = common profile, pPPPPPPPP.N = fully qualified (32-bit profile id),
// iN = implicit form (profile tag in the reader's/writer's implicit profile).
Tag ParseTag(const std::string & s, uint32_t implicitProfile)
{
    if (s.empty() || s == "a")
        return AnonymousTag();
    char k = s[0];
    std::string r = s.substr(1);
    if (k == 'c')
        return ContextTag(static_cast<uint8_t>(U(r)));
    if (k == 'm')
        return CommonTag(static_cast<uint32_t>(U(r)));
    if (k == 'i')
        return ProfileTag(implicitProfile, static_cast<uint32_t>(U(r)));
    if (k == 'p')
    {
        size_t dot = r.find('.');
        return ProfileTag(static_cast<uint32_t>(strtoul(r.substr(0, dot).c_str(), nullptr, 16)),
                          static_cast<uint32_t>(U(r.substr(dot + 1))));
    }
    return AnonymousTag();
}

void PTag(Tag t)
{
    char buf[64];
    StringBuilder<64> sb;
    t.AppendTo(sb);
    snprintf(buf, sizeof buf, "%s", sb.c_str());
    P(" tag=%s", buf);
}

TLVType ParseType(const std::string & s)
{
    if (s == "S")
        return kTLVType_Structure;
    if (s == "A")
        return kTLVType_Array;
    if (s == "L")
        return kTLVType_List;
    return static_cast<TLVType>(I(s));
}

// ---------------------------------------------------------------------------------------------------------
// Backing stores
// ---------------------------------------------------------------------------------------------------------

// Hands the reader its input in fixed-size chunks; gives the writer up to maxChunks buffers of chunk bytes.
class ChunkStore : public TLVBackingStore
{
public:
    std::vector<uint8_t> src;
    size_t chunk     = 8;
    size_t pos       = 0;
    size_t maxChunks = 4;
    std::vector<std::unique_ptr<uint8_t[]>> bufs;
    std::vector<uint32_t> lens;
    int newCalls = 0, finCalls = 0;

    CHIP_ERROR OnInit(TLVReader & reader, const uint8_t *& bufStart, uint32_t & bufLen) override
    {
        pos = 0;
        return GetNextBuffer(reader, bufStart, bufLen);
    }
    CHIP_ERROR GetNextBuffer(TLVReader &, const uint8_t *& bufStart, uint32_t & bufLen) override
    {
        size_t n = src.size() - pos;
        if (n > chunk)
            n = chunk;
        bufStart = n ? src.data() + pos : nullptr;
        bufLen   = static_cast<uint32_t>(n);
        pos += n;
        return CHIP_NO_ERROR;
    }
    CHIP_ERROR OnInit(TLVWriter & writer, uint8_t *& bufStart, uint32_t & bufLen) override
    {
        bufs.clear();
        lens.clear();
        return GetNewBuffer(writer, bufStart, bufLen);
    }
    CHIP_ERROR GetNewBuffer(TLVWriter &, uint8_t *& bufStart, uint32_t & bufLen) override
    {
        newCalls++;
        if (bufs.size() >= maxChunks)
        {
            bufStart = nullptr;
            bufLen   = 0;
            return CHIP_ERROR_NO_MEMORY;
        }
        bufs.emplace_back(new uint8_t[chunk]());
        lens.push_back(0);
        bufStart = bufs.back().get();
        bufLen   = static_cast<uint32_t>(chunk);
        return CHIP_NO_ERROR;
    }
    CHIP_ERROR FinalizeBuffer(TLVWriter &, uint8_t * bufStart, uint32_t bufLen) override
    {
        finCalls++;
        for (size_t i = 0; i < bufs.size(); i++)
            if (bufs[i].get() == bufStart)
                lens[i] = bufLen;
        return CHIP_NO_ERROR;
    }
    void Dump()
    {
        P(" chunks=%zu new=%d fin=%d data=", bufs.size(), newCalls, finCalls);
        std::vector<uint8_t> all;
        for (size_t i = 0; i < bufs.size(); i++)
        {
            P("%s%" PRIu32, i ? "," : "", lens[i]);
            all.insert(all.end(), bufs[i].get(), bufs[i].get() + lens[i]);
        }
        P(" bytes=");
        PHex(all.data(), all.size());
    }
};

// ---------------------------------------------------------------------------------------------------------
// Case state
// ---------------------------------------------------------------------------------------------------------

struct State
{
    // writer side
    std::vector<uint8_t> wbuf;
    ChunkStore wstore;
    std::vector<uint8_t> wvec;
    std::vector<std::shared_ptr<TLVWriter>> writers; // writers[0] is the root; OpenContainer pushes
    std::vector<TLVType> wouter;                     // StartContainer outer types
    int wkind = 0;                                   // 0 plain, 1 chunked, 2 vector, 3 circular

    // reader side
    std::vector<uint8_t> rbuf;
    ChunkStore rstore;
    std::vector<std::shared_ptr<TLVReader>> readers;
    std::vector<TLVType> router;
    bool contiguous = false;

    // circular buffer
    std::vector<uint8_t> cbufMem;
    std::unique_ptr<TLVCircularBuffer> cbuf;
    int evictLimit = -1, evicted = 0;

    // updater
    std::vector<uint8_t> ubuf;
    std::unique_ptr<TLVUpdater> upd;
    std::vector<TLVType> uouter;

    TLVWriter * W() { return writers.empty() ? nullptr : writers.back().get(); }
    TLVReader * R() { return readers.empty() ? nullptr : readers.back().get(); }
};

CHIP_ERROR EvictCB(TLVCircularBuffer &, void * appData, TLVReader & reader)
{
    State * st = static_cast<State *>(appData);
    P(" evict");
    PTag(reader.GetTag());
    P(" type=%d len=%" PRIu32, static_cast<int>(reader.GetType()), reader.GetLength());
    if (st->evictLimit >= 0 && st->evicted >= st->evictLimit)
    {
        P(" refuse");
        return CHIP_ERROR_NO_MEMORY;
    }
    st->evicted++;
    return CHIP_NO_ERROR;
}

void PElem(const TLVReader & r)
{
    P(" type=%d", static_cast<int>(r.GetType()));
    PTag(r.GetTag());
    P(" len=%" PRIu32 " ct=%d", r.GetLength(), static_cast<int>(r.GetContainerType()));
}

template <typename T>
void GetNum(TLVReader & r, const char * name, const char * fmt)
{
    T v{};
    CHIP_ERROR e = r.Get(v);
    P(" %s:", name);
    PErr(e);
    if (e == CHIP_NO_ERROR)
        P(fmt, v);
}

void GetOne(TLVReader & r, const std::string & k)
{
    if (k == "b")
    {
        bool v = false;
        CHIP_ERROR e = r.Get(v);
        P(" b:");
        PErr(e);
        if (e == CHIP_NO_ERROR)
            P("/%d", v ? 1 : 0);
    }
    else if (k == "i8")
        GetNum<int8_t>(r, "i8", "/%d");
    else if (k == "i16")
        GetNum<int16_t>(r, "i16", "/%d");
    else if (k == "i32")
        GetNum<int32_t>(r, "i32", "/%" PRId32);
    else if (k == "i64")
        GetNum<int64_t>(r, "i64", "/%" PRId64);
    else if (k == "u8")
        GetNum<uint8_t>(r, "u8", "/%u");
    else if (k == "u16")
        GetNum<uint16_t>(r, "u16", "/%u");
    else if (k == "u32")
        GetNum<uint32_t>(r, "u32", "/%" PRIu32);
    else if (k == "u64")
        GetNum<uint64_t>(r, "u64", "/%" PRIu64);
    else if (k == "f32")
    {
        float v = 0;
        CHIP_ERROR e = r.Get(v);
        P(" f32:");
        PErr(e);
        if (e == CHIP_NO_ERROR)
        {
            uint32_t bits;
            memcpy(&bits, &v, 4);
            P("/%08" PRIx32, bits);
        }
    }
    else if (k == "f64")
    {
        double v = 0;
        CHIP_ERROR e = r.Get(v);
        P(" f64:");
        PErr(e);
        if (e == CHIP_NO_ERROR)
        {
            uint64_t bits;
            memcpy(&bits, &v, 8);
            P("/%016" PRIx64, bits);
        }
    }
    else if (k == "bs")
    {
        ByteSpan v;
        CHIP_ERROR e = r.Get(v);
        P(" bs:");
        PErr(e);
        if (e == CHIP_NO_ERROR)
        {
            P("/");
            PHex(v.data(), v.size());
        }
    }
    else if (k == "cs")
    {
        CharSpan v;
        CHIP_ERROR e = r.Get(v);
        P(" cs:");
        PErr(e);
        if (e == CHIP_NO_ERROR)
        {
            P("/");
            PHex(reinterpret_cast<const uint8_t *>(v.data()), v.size());
        }
    }
    else if (k == "lsid")
    {
        Optional<LocalizedStringIdentifier> v;
        CHIP_ERROR e = r.Get(v);
        P(" lsid:");
        PErr(e);
        if (e == CHIP_NO_ERROR)
            P("/%s", v.HasValue() ? std::to_string(v.Value()).c_str() : "none");
    }
}

void GetAll(TLVReader & r)
{
    static const char * kinds[] = { "b", "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64", "f32", "f64", "bs", "cs" };
    for (const char * k : kinds)
        GetOne(r, k);
}

void GetBuffers(TLVReader & orig, int extra)
{
    // every call works on its own copy: reading string data advances a reader. Copies of a reader that pulls
    // its input from a backing store would share the store's position, so those readers are left alone.
    if (orig.GetBackingStore() != nullptr)
    {
        P(" bufs-skip");
        return;
    }
    uint32_t len = orig.GetLength();
    {
        TLVReader r = orig;
        size_t n = static_cast<size_t>(len) + static_cast<size_t>(extra < 0 ? 0 : extra);
        if (extra < 0 && len > 0)
            n = len - 1;
        std::vector<uint8_t> b(n + 1, 0xA5);
        CHIP_ERROR e = r.GetBytes(n ? b.data() : nullptr, n);
        P(" gbytes(%zu):", n);
        PErr(e);
        if (e == CHIP_NO_ERROR)
        {
            P("/");
            PHex(b.data(), len);
        }
    }
    {
        TLVReader r = orig;
        size_t n = static_cast<size_t>(len) + 1 + static_cast<size_t>(extra < 0 ? 0 : extra);
        if (extra < 0)
            n = len;
        std::vector<char> b(n + 1, 'Z');
        CHIP_ERROR e = r.GetString(n ? b.data() : nullptr, n);
        P(" gstr(%zu):", n);
        PErr(e);
        if (e == CHIP_NO_ERROR)
        {
            P("/");
            PText(b.data(), strnlen(b.data(), n));
        }
    }
    {
        TLVReader r = orig;
        uint8_t * d = nullptr;
        uint32_t dl = 0;
        CHIP_ERROR e = r.DupBytes(d, dl);
        P(" dupb:");
        PErr(e);
        if (e == CHIP_NO_ERROR)
        {
            P("/%" PRIu32 "/", dl);
            PHex(d, dl);
            Platform::MemoryFree(d);
        }
    }
    {
        TLVReader r = orig;
        char * d = nullptr;
        CHIP_ERROR e = r.DupString(d);
        P(" dups:");
        PErr(e);
        if (e == CHIP_NO_ERROR)
        {
            P("/");
            PText(d, strlen(d));
            Platform::MemoryFree(d);
        }
    }
    {
        TLVReader r = orig;
        const uint8_t * d = nullptr;
        CHIP_ERROR e = r.GetDataPtr(d);
        P(" dptr:");
        PErr(e);
        if (e == CHIP_NO_ERROR)
        {
            P("/");
            PHex(d, d ? len : 0);
        }
    }
}

int gSteps = 0;

CHIP_ERROR Walk(TLVReader & r, int depth, int flags)
{
    CHIP_ERROR err;
    while (true)
    {
        if (++gSteps > 4000)
        {
            P("\n  walk-limit");
            return CHIP_ERROR_INTERNAL;
        }
        err = r.Next();
        P("\n  d%d next", depth);
        PErr(err);
        if (err != CHIP_NO_ERROR)
            break;
        PElem(r);
        P(" lr=%" PRIu32, r.GetLengthRead());
        TLVType t = r.GetType();
        if (t == kTLVType_Structure || t == kTLVType_Array || t == kTLVType_List)
        {
            if (flags & 2)
            {
                // skip whole containers on odd depth when asked
                if ((depth & 1) == 1)
                {
                    P(" skip");
                    PErr(r.Skip());
                    continue;
                }
            }
            TLVType outer;
            err = r.EnterContainer(outer);
            P(" enter");
            PErr(err);
            if (err != CHIP_NO_ERROR)
                return err;
            CHIP_ERROR inner = Walk(r, depth + 1, flags);
            if (inner != CHIP_END_OF_TLV)
                return inner;
            err = r.ExitContainer(outer);
            P("\n  d%d exit", depth);
            PErr(err);
            if (err != CHIP_NO_ERROR)
                return err;
        }
        else
        {
            GetAll(r);
            if (flags & 1)
                GetBuffers(r, 0);
        }
    }
    return err;
}

// --- Debug dump capture
std::string gDump;
void DumpCB(const char * fmt, ...)
{
    char tmp[1024];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(tmp, sizeof tmp, fmt, ap);
    va_end(ap);
    if (n > 0)
        gDump.append(tmp, std::min(static_cast<size_t>(n), sizeof tmp - 1));
}

struct IterCtx
{
    int stopAt = -1;
    int seen   = 0;
    int match  = -1;
};

CHIP_ERROR IterCB(const TLVReader & r, size_t depth, void * ctx)
{
    IterCtx * c = static_cast<IterCtx *>(ctx);
    P(" [%zu %d", depth, static_cast<int>(r.GetType()));
    PTag(r.GetTag());
    P("]");
    c->seen++;
    if (c->stopAt >= 0 && c->seen > c->stopAt)
        return CHIP_ERROR_INVALID_ARGUMENT;
    return CHIP_NO_ERROR;
}

CHIP_ERROR NthCB(const TLVReader &, size_t, void * ctx)
{
    IterCtx * c = static_cast<IterCtx *>(ctx);
    return (c->seen++ == c->match) ? CHIP_ERROR_SENTINEL : CHIP_NO_ERROR;
}

// ---------------------------------------------------------------------------------------------------------
// Writer helpers (shared by the writer and the updater)
// ---------------------------------------------------------------------------------------------------------

const char * kFormats[] = { "%d", "%s-%u", "%08x", "%c%c%c", "%5.2f", "%lld:%llu", "[%-6s]", "%%%d%%", "%.3s|%s", "" };

template <typename WR>
bool PutOp(WR & w, const std::string & op, const std::vector<std::string> & a, uint32_t implicitProfile, CHIP_ERROR & e)
{
    auto tag = [&](size_t i) { return ParseTag(i < a.size() ? a[i] : "a", implicitProfile); };
    bool ps  = a.size() > 2 && a[2] == "p";
    if (op == "i8")
        e = ps ? w.Put(tag(0), static_cast<int8_t>(I(a[1])), true) : w.Put(tag(0), static_cast<int8_t>(I(a[1])));
    else if (op == "i16")
        e = ps ? w.Put(tag(0), static_cast<int16_t>(I(a[1])), true) : w.Put(tag(0), static_cast<int16_t>(I(a[1])));
    else if (op == "i32")
        e = ps ? w.Put(tag(0), static_cast<int32_t>(I(a[1])), true) : w.Put(tag(0), static_cast<int32_t>(I(a[1])));
    else if (op == "i64")
        e = ps ? w.Put(tag(0), static_cast<int64_t>(I(a[1])), true) : w.Put(tag(0), static_cast<int64_t>(I(a[1])));
    else if (op == "u8")
        e = ps ? w.Put(tag(0), static_cast<uint8_t>(U(a[1])), true) : w.Put(tag(0), static_cast<uint8_t>(U(a[1])));
    else if (op == "u16")
        e = ps ? w.Put(tag(0), static_cast<uint16_t>(U(a[1])), true) : w.Put(tag(0), static_cast<uint16_t>(U(a[1])));
    else if (op == "u32")
        e = ps ? w.Put(tag(0), static_cast<uint32_t>(U(a[1])), true) : w.Put(tag(0), static_cast<uint32_t>(U(a[1])));
    else if (op == "u64")
        e = ps ? w.Put(tag(0), static_cast<uint64_t>(U(a[1])), true) : w.Put(tag(0), static_cast<uint64_t>(U(a[1])));
    else if (op == "bool")
        e = w.PutBoolean(tag(0), U(a[1]) != 0);
    else if (op == "f32")
    {
        uint32_t bits = static_cast<uint32_t>(strtoul(a[1].c_str(), nullptr, 16));
        float f;
        memcpy(&f, &bits, 4);
        e = w.Put(tag(0), f);
    }
    else if (op == "f64")
    {
        uint64_t bits = strtoull(a[1].c_str(), nullptr, 16);
        double d;
        memcpy(&d, &bits, 8);
        e = w.Put(tag(0), d);
    }
    else if (op == "str")
    {
        std::string s = HexStr(a[1]);
        e             = w.PutString(tag(0), s.data(), static_cast<uint32_t>(s.size()));
    }
    else if (op == "strz")
    {
        std::string s = HexStr(a[1]);
        e             = w.PutString(tag(0), s.c_str());
    }
    else if (op == "bytes")
    {
        std::vector<uint8_t> b = Hex(a[1]);
        e                      = w.PutBytes(tag(0), b.data(), static_cast<uint32_t>(b.size()));
    }
    else if (op == "null")
        e = w.PutNull(tag(0));
    else
        return false;
    return true;
}

bool WriterExtraOp(TLVWriter & w, const std::string & op, const std::vector<std::string> & a, uint32_t ip, CHIP_ERROR & e)
{
    auto tag = [&](size_t i) { return ParseTag(i < a.size() ? a[i] : "a", ip); };
    if (op == "cstr")
    {
        std::string s = HexStr(a[1]);
        e             = w.PutString(tag(0), CharSpan(s.data(), s.size()));
    }
    else if (op == "bspan")
    {
        std::vector<uint8_t> b = Hex(a[1]);
        e                      = w.Put(tag(0), ByteSpan(b.data(), b.size()));
    }
    else if (op == "fmt")
    {
        // fmt <tag> <format index> <arg...>: fixed formats, typed arguments
        int k        = static_cast<int>(U(a[1]));
        Tag t        = tag(0);
        auto s       = [&](size_t i) { return i < a.size() ? HexStr(a[i]) : std::string(); };
        auto n       = [&](size_t i) { return i < a.size() ? I(a[i]) : 0; };
        switch (k)
        {
        case 0:
            e = w.PutStringF(t, kFormats[0], static_cast<int>(n(2)));
            break;
        case 1:
            e = w.PutStringF(t, kFormats[1], s(2).c_str(), static_cast<unsigned>(n(3)));
            break;
        case 2:
            e = w.PutStringF(t, kFormats[2], static_cast<unsigned>(n(2)));
            break;
        case 3:
            e = w.PutStringF(t, kFormats[3], static_cast<int>(n(2)), static_cast<int>(n(3)), static_cast<int>(n(4)));
            break;
        case 4:
            e = w.PutStringF(t, kFormats[4], static_cast<double>(n(2)) / 7.0);
            break;
        case 5:
            e = w.PutStringF(t, kFormats[5], static_cast<long long>(n(2)), static_cast<unsigned long long>(n(3)));
            break;
        case 6:
            e = w.PutStringF(t, kFormats[6], s(2).c_str());
            break;
        case 7:
            e = w.PutStringF(t, kFormats[7], static_cast<int>(n(2)));
            break;
        case 8:
            e = w.PutStringF(t, kFormats[8], s(2).c_str(), s(3).c_str());
            break;
        default: {
            std::string big = s(2);
            e               = w.PutStringF(t, "%s%s%s", big.c_str(), big.c_str(), big.c_str());
        }
        }
    }
    else if (op == "pre")
    {
        std::vector<uint8_t> b = Hex(a[2]);
        e = w.PutPreEncodedContainer(tag(0), ParseType(a[1]), b.data(), static_cast<uint32_t>(b.size()));
    }
    else if (op == "copyctb")
    {
        std::vector<uint8_t> b = Hex(a[1]);
        e                      = w.CopyContainer(tag(0), b.data(), static_cast<uint16_t>(b.size()));
    }
    else if (op == "reserve")
        e = w.ReserveBuffer(static_cast<uint32_t>(U(a[0])));
    else if (op == "unreserve")
        e = w.UnreserveBuffer(static_cast<uint32_t>(U(a[0])));
    else
        return false;
    return true;
}

// ---------------------------------------------------------------------------------------------------------
// Setup payload helpers
// ---------------------------------------------------------------------------------------------------------

// fields: ver,vid,pid,flow,rv,disc,pin   rv '-' = absent; disc Lnnnn (long) or Snn (short)
void ParseFields(const std::string & f, PayloadContents & p)
{
    std::vector<std::string> v;
    std::stringstream ss(f);
    std::string item;
    while (std::getline(ss, item, ','))
        v.push_back(item);
    while (v.size() < 7)
        v.push_back("0");
    p.version           = static_cast<uint8_t>(U(v[0]));
    p.vendorID          = static_cast<uint16_t>(U(v[1]));
    p.productID         = static_cast<uint16_t>(U(v[2]));
    p.commissioningFlow = static_cast<CommissioningFlow>(U(v[3]));
    if (v[4] != "-")
        p.rendezvousInformation.SetValue(RendezvousInformationFlags(static_cast<uint8_t>(U(v[4]))));
    if (!v[5].empty() && v[5][0] == 'S')
        p.discriminator.SetShortValue(static_cast<uint8_t>(U(v[5].substr(1)) & 0xF));
    else
        p.discriminator.SetLongValue(static_cast<uint16_t>(U(v[5].substr(1)) & 0xFFF));
    p.setUpPINCode = static_cast<uint32_t>(U(v[6]));
}

void PFields(const PayloadContents & p)
{
    P(" ver=%u vid=%u pid=%u flow=%u rv=%s disc=%s%u pin=%" PRIu32, p.version, p.vendorID, p.productID,
      static_cast<unsigned>(p.commissioningFlow),
      p.rendezvousInformation.HasValue() ? std::to_string(p.rendezvousInformation.Value().Raw()).c_str() : "-",
      p.discriminator.IsShortDiscriminator() ? "S" : "L",
      p.discriminator.IsShortDiscriminator() ? p.discriminator.GetShortValue() : p.discriminator.GetLongValue(),
      p.setUpPINCode);
}

void POptional(const SetupPayload & p)
{
    for (const auto & o : p.getAllOptionalVendorData())
    {
        P(" vd[%u t%d", o.tag, static_cast<int>(o.type));
        if (o.type == optionalQRCodeInfoTypeString)
        {
            P(" ");
            PText(o.data.data(), o.data.size());
        }
        else
            P(" %" PRId32, o.int32);
        P("]");
    }
    std::string sn;
    CHIP_ERROR e = p.getSerialNumber(sn);
    P(" sn:");
    PErr(e);
    if (e == CHIP_NO_ERROR)
    {
        P("/");
        PText(sn.data(), sn.size());
    }
}

// opt list: items separated by ';' : s<tag>=<hex> vendor string, i<tag>=<int> vendor int32, N=<hex> serial string,
// n=<u32> serial number, r<tag> remove vendor tag, R remove serial
void ApplyOptional(const std::string & list, SetupPayload & p)
{
    if (list == "-")
        return;
    std::stringstream ss(list);
    std::string it;
    while (std::getline(ss, it, ';'))
    {
        if (it.empty())
            continue;
        CHIP_ERROR e = CHIP_NO_ERROR;
        size_t eq    = it.find('=');
        std::string key = it.substr(0, eq), val = eq == std::string::npos ? "" : it.substr(eq + 1);
        if (key[0] == 's')
            e = p.addOptionalVendorData(static_cast<uint8_t>(U(key.substr(1))), HexStr(val));
        else if (key[0] == 'i')
            e = p.addOptionalVendorData(static_cast<uint8_t>(U(key.substr(1))), static_cast<int32_t>(I(val)));
        else if (key == "N")
            e = p.addSerialNumber(HexStr(val));
        else if (key == "n")
            e = p.addSerialNumber(static_cast<uint32_t>(U(val)));
        else if (key[0] == 'r')
            e = p.removeOptionalVendorData(static_cast<uint8_t>(U(key.substr(1))));
        else if (key == "R")
            e = p.removeSerialNumber();
        P(" opt(%s)", key.c_str());
        PErr(e);
    }
}

// ---------------------------------------------------------------------------------------------------------
// Operation dispatch
// ---------------------------------------------------------------------------------------------------------

void RunOp(State & st, const std::string & op, const std::vector<std::string> & a)
{
    P("%s", op.c_str());
    CHIP_ERROR e = CHIP_NO_ERROR;
    std::string grp = op.substr(0, op.find('.'));
    std::string sub = op.find('.') == std::string::npos ? "" : op.substr(op.find('.') + 1);

    if (grp == "W")
    {
        // ---- writer
        if (sub == "init" || sub == "initchunks" || sub == "initvec" || sub == "initcirc")
        {
            st.writers.clear();
            st.wouter.clear();
            if (sub == "init")
            {
                st.wkind = 0;
                st.wbuf.assign(U(a[0]), 0xEE);
                st.writers.emplace_back(new TLVWriter());
                st.W()->Init(st.wbuf.data(), st.wbuf.size());
            }
            else if (sub == "initchunks")
            {
                st.wkind            = 1;
                st.wstore.chunk     = U(a[0]);
                st.wstore.maxChunks = U(a[1]);
                st.wstore.newCalls = st.wstore.finCalls = 0;
                st.writers.emplace_back(new TLVWriter());
                e = st.W()->Init(st.wstore, a.size() > 2 ? static_cast<uint32_t>(U(a[2])) : UINT32_MAX);
                PErr(e);
            }
            else if (sub == "initvec")
            {
                st.wkind = 2;
                st.wvec.clear();
                st.writers.emplace_back(new TlvVectorWriter(st.wvec));
            }
            else
            {
                st.wkind = 3;
                if (!st.cbuf)
                {
                    P(" no-circ");
                    return;
                }
                auto * cw = new CircularTLVWriter();
                st.writers.emplace_back(cw);
                cw->Init(*st.cbuf);
            }
            return;
        }
        TLVWriter * w = st.W();
        if (!w)
        {
            P(" no-writer");
            return;
        }
        if (sub == "ipid")
        {
            w->ImplicitProfileId = static_cast<uint32_t>(strtoul(a[0].c_str(), nullptr, 16));
            return;
        }
        if (PutOp(*w, sub, a, w->ImplicitProfileId, e) || WriterExtraOp(*w, sub, a, w->ImplicitProfileId, e))
        {
            PErr(e);
            return;
        }
        if (sub == "start")
        {
            TLVType outer;
            e = w->StartContainer(ParseTag(a[0], w->ImplicitProfileId), ParseType(a[1]), outer);
            if (e == CHIP_NO_ERROR)
                st.wouter.push_back(outer);
            PErr(e);
        }
        else if (sub == "end")
        {
            TLVType outer = st.wouter.empty() ? kTLVType_NotSpecified : st.wouter.back();
            if (a.size() > 0)
                outer = static_cast<TLVType>(I(a[0]));
            e = w->EndContainer(outer);
            if (e == CHIP_NO_ERROR && !st.wouter.empty())
                st.wouter.pop_back();
            PErr(e);
        }
        else if (sub == "open")
        {
            std::shared_ptr<TLVWriter> c(new TLVWriter());
            e = w->OpenContainer(ParseTag(a[0], w->ImplicitProfileId), ParseType(a[1]), *c);
            PErr(e);
            if (e == CHIP_NO_ERROR)
                st.writers.push_back(std::move(c));
        }
        else if (sub == "close")
        {
            if (st.writers.size() < 2)
            {
                P(" no-open");
                return;
            }
            std::shared_ptr<TLVWriter> c = st.writers.back();
            st.writers.pop_back();
            e = st.W()->CloseContainer(*c);
            PErr(e);
        }
        else if (sub == "copyel" || sub == "copyct")
        {
            TLVReader * r = st.R();
            if (!r)
            {
                P(" no-reader");
                return;
            }
            bool withTag = !a.empty();
            Tag t        = withTag ? ParseTag(a[0], w->ImplicitProfileId) : AnonymousTag();
            if (sub == "copyel")
                e = withTag ? w->CopyElement(t, *r) : w->CopyElement(*r);
            else
                e = withTag ? w->CopyContainer(t, *r) : w->CopyContainer(*r);
            PErr(e);
        }
        else if (sub == "fin")
        {
            PErr(w->Finalize());
        }
        else if (sub == "state")
        {
            P(" lw=%" PRIu32 " free=%" PRIu32 " ct=%d init=%d", w->GetLengthWritten(), w->GetRemainingFreeLength(),
              static_cast<int>(w->GetContainerType()), w->IsInitialized() ? 1 : 0);
        }
        else if (sub == "dump")
        {
            TLVWriter * root = st.writers.front().get();
            P(" lw=%" PRIu32, root->GetLengthWritten());
            if (st.wkind == 0)
            {
                P(" bytes=");
                PHex(st.wbuf.data(), std::min<size_t>(root->GetLengthWritten(), st.wbuf.size()));
            }
            else if (st.wkind == 1)
                st.wstore.Dump();
            else if (st.wkind == 2)
            {
                P(" bytes=");
                PHex(st.wvec.data(), st.wvec.size());
            }
            else if (st.cbuf)
                P(" circ=%" PRIu32 "/%" PRIu32, st.cbuf->DataLength(), st.cbuf->AvailableDataLength());
        }
        else
            P(" unknown-op");
        return;
    }

    if (grp == "R")
    {
        // ---- reader
        if (sub == "init" || sub == "initc" || sub == "initcont" || sub == "fromw" || sub == "initcirc" || sub == "initmax")
        {
            st.readers.clear();
            st.router.clear();
            st.contiguous = false;
            if (sub == "init" || sub == "initmax")
            {
                st.rbuf = Hex(a[0]);
                st.readers.emplace_back(new TLVReader());
                st.R()->Init(st.rbuf.data(), st.rbuf.size());
            }
            else if (sub == "initc")
            {
                st.rstore.src   = Hex(a[0]);
                st.rstore.chunk = U(a[1]);
                st.readers.emplace_back(new TLVReader());
                e = st.R()->Init(st.rstore, a.size() > 2 ? static_cast<uint32_t>(U(a[2])) : UINT32_MAX);
                PErr(e);
            }
            else if (sub == "initcont")
            {
                st.rbuf = Hex(a[0]);
                auto * cr = new ContiguousBufferTLVReader();
                st.readers.emplace_back(cr);
                cr->Init(st.rbuf.data(), st.rbuf.size());
                st.contiguous = true;
            }
            else if (sub == "fromw")
            {
                if (st.wkind == 0)
                    st.rbuf.assign(st.wbuf.begin(), st.wbuf.begin() + (st.writers.empty() ? 0 : st.writers.front()->GetLengthWritten()));
                else if (st.wkind == 2)
                    st.rbuf = st.wvec;
                else
                {
                    st.rbuf.clear();
                    for (size_t i = 0; i < st.wstore.bufs.size(); i++)
                        st.rbuf.insert(st.rbuf.end(), st.wstore.bufs[i].get(), st.wstore.bufs[i].get() + st.wstore.lens[i]);
                }
                st.readers.emplace_back(new TLVReader());
                st.R()->Init(st.rbuf.data(), st.rbuf.size());
                P(" n=%zu", st.rbuf.size());
            }
            else
            {
                if (!st.cbuf)
                {
                    P(" no-circ");
                    return;
                }
                auto * cr = new CircularTLVReader();
                st.readers.emplace_back(cr);
                cr->Init(*st.cbuf);
            }
            return;
        }
        TLVReader * r = st.R();
        if (!r)
        {
            P(" no-reader");
            return;
        }
        uint32_t ip = r->ImplicitProfileId;
        if (sub == "ipid")
            r->ImplicitProfileId = static_cast<uint32_t>(strtoul(a[0].c_str(), nullptr, 16));
        else if (sub == "next" || sub == "nextt" || sub == "nextty" || sub == "expect" || sub == "expectty")
        {
            if (sub == "next")
                e = r->Next();
            else if (sub == "nextt")
                e = r->Next(ParseTag(a[0], ip));
            else if (sub == "nextty")
                e = r->Next(ParseType(a[0]), ParseTag(a[1], ip));
            else if (sub == "expect")
                e = r->Expect(ParseTag(a[0], ip));
            else
                e = r->Expect(ParseType(a[0]), ParseTag(a[1], ip));
            PErr(e);
            PElem(*r);
        }
        else if (sub == "info")
        {
            PElem(*r);
            P(" lr=%" PRIu32 " rem=%" PRIu32 " tot=%" PRIu32 " dbl=%d", r->GetLengthRead(), r->GetRemainingLength(),
              r->GetTotalLength(), r->IsElementDouble() ? 1 : 0);
        }
        else if (sub == "get")
        {
            for (const auto & k : a)
                GetOne(*r, k);
        }
        else if (sub == "getall")
            GetAll(*r);
        else if (sub == "bufs")
            GetBuffers(*r, a.empty() ? 0 : static_cast<int>(I(a[0])));
        else if (sub == "gbytes" || sub == "gstr")
        {
            size_t n = U(a[0]);
            std::vector<char> b(n + 1, 'Z');
            e = sub == "gbytes" ? r->GetBytes(reinterpret_cast<uint8_t *>(b.data()), n) : r->GetString(b.data(), n);
            PErr(e);
            if (e == CHIP_NO_ERROR)
            {
                P("/");
                if (sub == "gbytes")
                    PHex(reinterpret_cast<uint8_t *>(b.data()), std::min<size_t>(n, r->GetLength()));
                else
                    PText(b.data(), strnlen(b.data(), n));
            }
        }
        else if (sub == "enter")
        {
            TLVType outer;
            e = r->EnterContainer(outer);
            if (e == CHIP_NO_ERROR)
                st.router.push_back(outer);
            PErr(e);
            P(" ct=%d", static_cast<int>(r->GetContainerType()));
        }
        else if (sub == "exit")
        {
            TLVType outer = st.router.empty() ? kTLVType_NotSpecified : st.router.back();
            e             = r->ExitContainer(outer);
            if (e == CHIP_NO_ERROR && !st.router.empty())
                st.router.pop_back();
            PErr(e);
            P(" ct=%d", static_cast<int>(r->GetContainerType()));
        }
        else if (sub == "open")
        {
            std::shared_ptr<TLVReader> c;
            if (st.contiguous)
            {
                auto * cc = new ContiguousBufferTLVReader();
                c = std::shared_ptr<TLVReader>(cc);
                e = static_cast<ContiguousBufferTLVReader *>(r)->OpenContainer(*cc);
            }
            else
            {
                c = std::make_shared<TLVReader>();
                e = r->OpenContainer(*c);
            }
            PErr(e);
            if (e == CHIP_NO_ERROR)
                st.readers.push_back(std::move(c));
        }
        else if (sub == "close")
        {
            if (st.readers.size() < 2)
            {
                P(" no-open");
                return;
            }
            std::shared_ptr<TLVReader> c = st.readers.back();
            st.readers.pop_back();
            e = st.R()->CloseContainer(*c);
            PErr(e);
        }
        else if (sub == "skip")
            PErr(r->Skip());
        else if (sub == "veoc")
            PErr(r->VerifyEndOfContainer());
        else if (sub == "find")
        {
            TLVReader res;
            e = r->FindElementWithTag(ParseTag(a[0], ip), res);
            PErr(e);
            if (e == CHIP_NO_ERROR)
            {
                PElem(res);
                GetAll(res);
            }
        }
        else if (sub == "cnt")
        {
            size_t n = 0;
            e        = r->CountRemainingInContainer(&n);
            PErr(e);
            P(" n=%zu", n);
        }
        else if (sub == "gsv" || sub == "gbv")
        {
            if (!st.contiguous)
            {
                P(" not-contiguous");
                return;
            }
            auto * cr = static_cast<ContiguousBufferTLVReader *>(r);
            if (sub == "gsv")
            {
                Span<const char> s;
                e = cr->GetStringView(s);
                PErr(e);
                if (e == CHIP_NO_ERROR)
                    PText(s.data(), s.size());
            }
            else
            {
                ByteSpan s;
                e = cr->GetByteView(s);
                PErr(e);
                if (e == CHIP_NO_ERROR)
                    PHex(s.data(), s.size());
            }
        }
        else if (sub == "walk")
        {
            gSteps = 0;
            e      = Walk(*r, 0, a.empty() ? 0 : static_cast<int>(U(a[0])));
            P("\n  walk-end");
            PErr(e);
        }
        else
            P(" unknown-op");
        return;
    }

    if (grp == "U" || grp == "D")
    {
        TLVReader * r = st.R();
        if (!r)
        {
            P(" no-reader");
            return;
        }
        bool rec = !a.empty() && a.back() == "r";
        if (op == "U.count")
        {
            size_t n = 0;
            e        = a.empty() ? Utilities::Count(*r, n) : Utilities::Count(*r, n, rec);
            PErr(e);
            P(" n=%zu", n);
        }
        else if (op == "U.find")
        {
            TLVReader res;
            e = a.size() > 1 ? Utilities::Find(*r, ParseTag(a[0], r->ImplicitProfileId), res, rec)
                             : Utilities::Find(*r, ParseTag(a[0], r->ImplicitProfileId), res);
            PErr(e);
            if (e == CHIP_NO_ERROR)
            {
                PElem(res);
                GetAll(res);
            }
        }
        else if (op == "U.findn")
        {
            TLVReader res;
            IterCtx c;
            c.match = static_cast<int>(U(a[0]));
            e       = a.size() > 1 ? Utilities::Find(*r, NthCB, &c, res, rec) : Utilities::Find(*r, NthCB, &c, res);
            PErr(e);
            if (e == CHIP_NO_ERROR)
                PElem(res);
        }
        else if (op == "U.iter")
        {
            IterCtx c;
            c.stopAt = a.size() > 1 ? static_cast<int>(I(a[0])) : -1;
            e        = a.empty() ? Utilities::Iterate(*r, IterCB, &c) : Utilities::Iterate(*r, IterCB, &c, rec);
            PErr(e);
        }
        else if (op == "D.dump")
        {
            gDump.clear();
            e = Debug::Dump(*r, DumpCB);
            PErr(e);
            P("\n");
            PText(gDump.data(), gDump.size());
        }
        else if (op == "D.names")
        {
            for (int t : { -1, -2, 0, 4, 8, 10, 12, 16, 20, 21, 22, 23, 99 })
                P(" %s", Debug::DecodeType(static_cast<TLVType>(t)));
            for (int c = 0; c < 8; c++)
                P(" %s", Debug::DecodeTagControl(static_cast<TLVTagControl>(c << 5)));
        }
        else
            P(" unknown-op");
        return;
    }

    if (grp == "C")
    {
        // ---- circular buffer
        if (sub == "init")
        {
            st.cbufMem.assign(U(a[0]), 0);
            size_t headOff = a.size() > 1 ? U(a[1]) : 0;
            if (headOff)
                st.cbuf.reset(new TLVCircularBuffer(st.cbufMem.data(), static_cast<uint32_t>(st.cbufMem.size()),
                                                    st.cbufMem.data() + headOff));
            else
                st.cbuf.reset(new TLVCircularBuffer(st.cbufMem.data(), static_cast<uint32_t>(st.cbufMem.size())));
            st.cbuf->mProcessEvictedElement = EvictCB;
            st.cbuf->mAppData               = &st;
            st.evicted                      = 0;
            st.evictLimit                   = a.size() > 2 ? static_cast<int>(I(a[2])) : -1;
            return;
        }
        if (!st.cbuf)
        {
            P(" no-circ");
            return;
        }
        if (sub == "evict")
            PErr(st.cbuf->EvictHead());
        else if (sub == "state")
        {
            P(" len=%" PRIu32 " avail=%" PRIu32 " total=%" PRIu32 " head=%td tail=%td", st.cbuf->DataLength(),
              st.cbuf->AvailableDataLength(), st.cbuf->GetTotalDataLength(), st.cbuf->QueueHead() - st.cbufMem.data(),
              st.cbuf->QueueTail() - st.cbufMem.data());
            P(" mem=");
            PHex(st.cbufMem.data(), st.cbufMem.size());
        }
        else
            P(" unknown-op");
        return;
    }

    if (grp == "P")
    {
        // ---- updater
        if (sub == "init")
        {
            std::vector<uint8_t> d = Hex(a[0]);
            size_t maxLen          = U(a[1]);
            st.ubuf.assign(std::max(maxLen, d.size()) + 16, 0xEE);
            std::copy(d.begin(), d.end(), st.ubuf.begin());
            st.upd.reset(new TLVUpdater());
            st.uouter.clear();
            PErr(st.upd->Init(st.ubuf.data(), static_cast<uint32_t>(d.size()), static_cast<uint32_t>(maxLen)));
            return;
        }
        if (sub == "initr")
        {
            TLVReader * r = st.R();
            if (!r)
            {
                P(" no-reader");
                return;
            }
            st.upd.reset(new TLVUpdater());
            st.uouter.clear();
            PErr(st.upd->Init(*r, static_cast<uint32_t>(U(a[0]))));
            return;
        }
        if (!st.upd)
        {
            P(" no-updater");
            return;
        }
        TLVUpdater & u = *st.upd;
        uint32_t ip    = u.GetImplicitProfileId();
        if (sub == "ipid")
            u.SetImplicitProfileId(static_cast<uint32_t>(strtoul(a[0].c_str(), nullptr, 16)));
        else if (sub == "next")
        {
            PErr(u.Next());
            P(" type=%d", static_cast<int>(u.GetType()));
            PTag(u.GetTag());
            P(" len=%" PRIu32 " lr=%" PRIu32 " rem=%" PRIu32 " lw=%" PRIu32 " free=%" PRIu32, u.GetLength(), u.GetLengthRead(),
              u.GetRemainingLength(), u.GetLengthWritten(), u.GetRemainingFreeLength());
        }
        else if (sub == "move")
            PErr(u.Move());
        else if (sub == "moveend")
            u.MoveUntilEnd();
        else if (sub == "enter")
        {
            TLVType outer;
            e = u.EnterContainer(outer);
            if (e == CHIP_NO_ERROR)
                st.uouter.push_back(outer);
            PErr(e);
        }
        else if (sub == "exit")
        {
            TLVType outer = st.uouter.empty() ? kTLVType_NotSpecified : st.uouter.back();
            e             = u.ExitContainer(outer);
            if (e == CHIP_NO_ERROR && !st.uouter.empty())
                st.uouter.pop_back();
            PErr(e);
        }
        else if (sub == "start")
        {
            TLVType outer;
            e = u.StartContainer(ParseTag(a[0], ip), ParseType(a[1]), outer);
            if (e == CHIP_NO_ERROR)
                st.uouter.push_back(outer);
            PErr(e);
        }
        else if (sub == "end")
        {
            TLVType outer = st.uouter.empty() ? kTLVType_NotSpecified : st.uouter.back();
            e             = u.EndContainer(outer);
            if (e == CHIP_NO_ERROR && !st.uouter.empty())
                st.uouter.pop_back();
            PErr(e);
        }
        else if (sub == "getall")
        {
            TLVReader r;
            u.GetReader(r);
            GetAll(r);
        }
        else if (sub == "fin")
            PErr(u.Finalize());
        else if (sub == "dump")
        {
            P(" lw=%" PRIu32 " free=%" PRIu32 " bytes=", u.GetLengthWritten(), u.GetRemainingFreeLength());
            PHex(st.ubuf.data(), std::min<size_t>(u.GetLengthWritten(), st.ubuf.size()));
        }
        else if (PutOp(u, sub, a, ip, e))
            PErr(e);
        else
            P(" unknown-op");
        return;
    }

    if (grp == "H")
    {
        // ---- message framing
        if (sub == "penc")
        {
            PacketHeader h;
            h.SetSecurityFlags(static_cast<uint8_t>(U(a[0])));
            h.SetSessionId(static_cast<uint16_t>(U(a[1])));
            h.SetMessageCounter(static_cast<uint32_t>(U(a[2])));
            if (a[3] != "-")
                h.SetSourceNodeId(static_cast<NodeId>(strtoull(a[3].c_str(), nullptr, 16)));
            if (a[4] != "-")
                h.SetDestinationNodeId(static_cast<NodeId>(strtoull(a[4].c_str(), nullptr, 16)));
            if (a[5] != "-")
                h.SetDestinationGroupId(static_cast<GroupId>(U(a[5])));
            if (a.size() > 7 && a[7] != "0")
                h.SetMessageFlags(static_cast<uint8_t>(h.GetMessageFlags() | U(a[7])));
            std::vector<uint8_t> buf(U(a[6]) + 4, 0xEE);
            uint16_t n = 0;
            e          = h.Encode(buf.data(), U(a[6]), &n);
            PErr(e);
            P(" sz=%u n=%u bytes=", h.EncodeSizeBytes(), n);
            PHex(buf.data(), e == CHIP_NO_ERROR ? n : 0);
        }
        else if (sub == "pdec")
        {
            std::vector<uint8_t> d = Hex(a[0]);
            PacketHeader h;
            uint16_t n = 0;
            e          = h.Decode(d.data(), d.size(), &n);
            PErr(e);
            P(" n=%u mf=%02x sf=%02x sid=%u ctr=%" PRIu32 " st=%u", n, h.GetMessageFlags(), h.GetSecurityFlags(), h.GetSessionId(),
              h.GetMessageCounter(), static_cast<unsigned>(h.GetSessionType()));
            P(" src=%s", h.GetSourceNodeId().HasValue() ? std::to_string(h.GetSourceNodeId().Value()).c_str() : "-");
            P(" dst=%s", h.GetDestinationNodeId().HasValue() ? std::to_string(h.GetDestinationNodeId().Value()).c_str() : "-");
            P(" grp=%s", h.GetDestinationGroupId().HasValue() ? std::to_string(h.GetDestinationGroupId().Value()).c_str() : "-");
            P(" enc=%d mic=%u sz=%u", h.IsEncrypted() ? 1 : 0, h.MICTagLength(), h.EncodeSizeBytes());
            if (e == CHIP_NO_ERROR && a.size() > 1)
            {
                // round trip: re-encode what was decoded
                std::vector<uint8_t> out(64, 0);
                uint16_t m = 0;
                CHIP_ERROR e2 = h.Encode(out.data(), out.size(), &m);
                P(" re");
                PErr(e2);
                P("/");
                PHex(out.data(), e2 == CHIP_NO_ERROR ? m : 0);
            }
            if (e == CHIP_NO_ERROR && h.IsEncrypted() && d.size() >= n)
            {
                MessageAuthenticationCode mac;
                uint16_t ml = 0;
                CHIP_ERROR e3 = mac.Decode(h, d.data() + n, d.size() - n, &ml);
                P(" mac");
                PErr(e3);
                P("/%u", ml);
                if (e3 == CHIP_NO_ERROR)
                {
                    std::vector<uint8_t> mo(32, 0);
                    uint16_t mn = 0;
                    CHIP_ERROR e4 = mac.Encode(h, mo.data(), mo.size(), &mn);
                    P(" macenc");
                    PErr(e4);
                    P("/");
                    PHex(mo.data(), e4 == CHIP_NO_ERROR ? mn : 0);
                }
            }
        }
        else if (sub == "yenc")
        {
            PayloadHeader h;
            uint8_t fl = static_cast<uint8_t>(U(a[0]));
            h.SetMessageType(Protocols::Id(static_cast<VendorId>(U(a[2])), static_cast<uint16_t>(U(a[3]))),
                             static_cast<uint8_t>(U(a[4])));
            h.SetExchangeID(static_cast<uint16_t>(U(a[1])));
            h.SetInitiator(fl & 1);
            h.SetNeedsAck(fl & 2);
            if (a[5] != "-")
                h.SetAckMessageCounter(static_cast<uint32_t>(U(a[5])));
            std::vector<uint8_t> buf(U(a[6]) + 4, 0xEE);
            uint16_t n = 0;
            e          = h.Encode(buf.data(), U(a[6]), &n);
            PErr(e);
            P(" sz=%u n=%u bytes=", h.EncodeSizeBytes(), n);
            PHex(buf.data(), e == CHIP_NO_ERROR ? n : 0);
        }
        else if (sub == "ydec")
        {
            std::vector<uint8_t> d = Hex(a[0]);
            PayloadHeader h;
            uint16_t n = 0;
            e          = h.Decode(d.data(), d.size(), &n);
            PErr(e);
            P(" n=%u xf=%02x xid=%u vid=%u proto=%u type=%u init=%d ack=%s needs=%d sz=%u", n, h.GetExchangeFlags(),
              h.GetExchangeID(), static_cast<unsigned>(h.GetProtocolID().GetVendorId()), h.GetProtocolID().GetProtocolId(),
              h.GetMessageType(), h.IsInitiator() ? 1 : 0,
              h.GetAckMessageCounter().HasValue() ? std::to_string(h.GetAckMessageCounter().Value()).c_str() : "-",
              h.NeedsAck() ? 1 : 0, h.EncodeSizeBytes());
            if (e == CHIP_NO_ERROR && a.size() > 1)
            {
                std::vector<uint8_t> out(64, 0);
                uint16_t m = 0;
                CHIP_ERROR e2 = h.Encode(out.data(), out.size(), &m);
                P(" re");
                PErr(e2);
                P("/");
                PHex(out.data(), e2 == CHIP_NO_ERROR ? m : 0);
            }
        }
        else
            P(" unknown-op");
        return;
    }

    if (grp == "Q" || grp == "M" || grp == "B" || grp == "A" || grp == "S")
    {
        // ---- onboarding payloads
        if (op == "Q.gen")
        {
            SetupPayload p;
            ParseFields(a[0], p);
            ApplyOptional(a[1], p);
            QRCodeSetupPayloadGenerator g(p);
            g.SetAllowInvalidPayload(a.size() > 2 && a[2] == "1");
            std::string s;
            e = g.payloadBase38RepresentationWithAutoTLVBuffer(s);
            P(" auto");
            PErr(e);
            P("/%s", s.c_str());
            std::vector<uint8_t> tlv(a.size() > 3 ? U(a[3]) : 0);
            std::string s2;
            e = g.payloadBase38Representation(s2, tlv.empty() ? nullptr : tlv.data(), static_cast<uint32_t>(tlv.size()));
            P(" buf");
            PErr(e);
            P("/%s", s2.c_str());
        }
        else if (op == "Q.basic")
        {
            PayloadContents p;
            ParseFields(a[0], p);
            char buf[160];
            memset(buf, 'Z', sizeof buf);
            MutableCharSpan out(buf, std::min<size_t>(U(a[1]), sizeof buf));
            e = QRCodeBasicSetupPayloadGenerator(p).payloadBase38Representation(out);
            PErr(e);
            if (e == CHIP_NO_ERROR)
            {
                P("/");
                PText(out.data(), out.size());
            }
        }
        else if (op == "Q.parse")
        {
            std::string s = HexStr(a[0]);
            SetupPayload p;
            e = QRCodeSetupPayloadParser(s).populatePayload(p);
            PErr(e);
            if (e == CHIP_NO_ERROR)
            {
                PFields(p);
                POptional(p);
            }
            std::vector<SetupPayload> ps;
            e = QRCodeSetupPayloadParser(s).populatePayloads(ps);
            P(" multi");
            PErr(e);
            P("/%zu", ps.size());
            for (auto & q : ps)
                PFields(q);
            std::string ex = QRCodeSetupPayloadParser::ExtractPayload(s);
            P(" extract=");
            PText(ex.data(), ex.size());
        }
        else if (op == "M.gen")
        {
            PayloadContents p;
            ParseFields(a[0], p);
            ManualSetupPayloadGenerator g(p);
            g.SetForceShortCode(a[1] == "1");
            g.SetAllowInvalidPayload(a[2] == "1");
            std::string s;
            e = g.payloadDecimalStringRepresentation(s);
            PErr(e);
            P("/%s", s.c_str());
            char buf[40];
            memset(buf, 'Z', sizeof buf);
            MutableCharSpan out(buf, std::min<size_t>(U(a[3]), sizeof buf));
            e = g.payloadDecimalStringRepresentation(out);
            P(" span");
            PErr(e);
            if (e == CHIP_NO_ERROR)
            {
                P("/");
                PText(out.data(), out.size());
            }
        }
        else if (op == "M.parse")
        {
            SetupPayload p;
            e = ManualSetupPayloadParser(HexStr(a[0])).populatePayload(p);
            PErr(e);
            if (e == CHIP_NO_ERROR)
                PFields(p);
        }
        else if (op == "B.enc")
        {
            std::vector<uint8_t> in = Hex(a[0]);
            char buf[512];
            memset(buf, 'Z', sizeof buf);
            MutableCharSpan out(buf, std::min<size_t>(U(a[1]), sizeof buf));
            e = base38Encode(ByteSpan(in.data(), in.size()), out);
            PErr(e);
            P(" len=%zu", base38EncodedLength(in.size()));
            if (e == CHIP_NO_ERROR)
            {
                P("/");
                PText(out.data(), out.size());
                P(" nul=%d", (out.size() < U(a[1]) && buf[out.size()] == '\0') ? 1 : 0);
            }
        }
        else if (op == "B.dec")
        {
            std::vector<uint8_t> out;
            e = base38Decode(HexStr(a[0]), out);
            PErr(e);
            P("/");
            PHex(out.data(), out.size());
        }
        else if (op == "A.parse")
        {
            std::vector<uint8_t> in = Hex(a[0]);
            SetupPayloadData::AdditionalDataPayload p;
            e = AdditionalDataPayloadParser(in.data(), in.size()).populatePayload(p);
            PErr(e);
            P("/");
            PText(p.rotatingDeviceId.data(), p.rotatingDeviceId.size());
        }
        else if (op == "S.valid")
        {
            PayloadContents p;
            ParseFields(a[0], p);
            using VM = PayloadContents::ValidationMode;
            P(" qr=%d/%d manual=%d/%d pin=%d", p.isValidQRCodePayload(VM::kProduce) ? 1 : 0,
              p.isValidQRCodePayload(VM::kConsume) ? 1 : 0, p.isValidManualCode(VM::kProduce) ? 1 : 0,
              p.isValidManualCode(VM::kConsume) ? 1 : 0, PayloadContents::IsValidSetupPIN(p.setUpPINCode) ? 1 : 0);
        }
        else if (op == "S.opt")
        {
            SetupPayload p;
            ParseFields(a[0], p);
            ApplyOptional(a[1], p);
            POptional(p);
            if (a.size() > 2)
            {
                OptionalQRCodeInfo info;
                e = p.getOptionalVendorData(static_cast<uint8_t>(U(a[2])), info);
                P(" get");
                PErr(e);
                if (e == CHIP_NO_ERROR)
                    P("/t%d", static_cast<int>(info.type));
            }
        }
        else if (op == "S.str")
        {
            std::vector<SetupPayload> ps;
            e = SetupPayload::FromStringRepresentation(HexStr(a[0]), ps);
            PErr(e);
            P("/%zu", ps.size());
            for (auto & q : ps)
            {
                PFields(q);
                POptional(q);
            }
        }
        else
            P(" unknown-op");
        return;
    }

    if (grp == "J")
    {
        // ---- JSON <-> TLV
        if (sub == "t2j")
        {
            std::vector<uint8_t> in = Hex(a[0]);
            std::string js;
            e = TlvToJson(ByteSpan(in.data(), in.size()), js);
            PErr(e);
            P("\n");
            PText(js.data(), js.size());
        }
        else if (sub == "j2t")
        {
            std::string js = HexStr(a[0]);
            std::vector<uint8_t> buf(U(a[1]) + 4, 0xEE);
            MutableByteSpan out(buf.data(), U(a[1]));
            e = JsonToTlv(js, out);
            PErr(e);
            P(" n=%zu/", out.size());
            PHex(out.data(), e == CHIP_NO_ERROR ? out.size() : 0);
        }
        else if (sub == "j2tw")
        {
            // into a caller-provided writer, then Finalize
            std::string js = HexStr(a[0]);
            std::vector<uint8_t> buf(U(a[1]) + 4, 0xEE);
            TLVWriter w;
            w.Init(buf.data(), U(a[1]));
            e = JsonToTlv(js, w);
            PErr(e);
            if (e == CHIP_NO_ERROR)
            {
                e = w.Finalize();
                P(" fin");
                PErr(e);
                P("/");
                PHex(buf.data(), e == CHIP_NO_ERROR ? w.GetLengthWritten() : 0);
            }
        }
        else if (sub == "tag")
        {
            Tag t = AnonymousTag();
            e     = ConvertTlvTag(static_cast<uint32_t>(U(a[0])), t);
            PErr(e);
            PTag(t);
        }
        else if (sub == "old")
        {
            std::vector<uint8_t> in = Hex(a[0]);
            TLVReader r;
            r.Init(in.data(), in.size());
            e = r.Next();
            P(" next");
            PErr(e);
            Json::Value root;
            e = TlvToJson(r, root);
            PErr(e);
            std::string s = JsonToString(root);
            P("\n");
            PText(s.data(), s.size());
        }
        else if (sub == "pretty")
        {
            std::string s = PrettyPrintJsonString(HexStr(a[0]));
            P("\n");
            PText(s.data(), s.size());
        }
        else
            P(" unknown-op");
        return;
    }
    P(" unknown-op");
}

std::vector<std::string> Split(const std::string & line)
{
    std::vector<std::string> v;
    std::stringstream ss(line);
    std::string t;
    while (ss >> t)
        v.push_back(t);
    return v;
}

struct Case
{
    std::string id, bucket;
    std::vector<std::string> ops;
};

void RunCase(const Case & c)
{
    Platform::MemoryInit();
    State st;
    gOut.clear();
    for (const auto & line : c.ops)
    {
        std::vector<std::string> t = Split(line);
        if (t.empty())
            continue;
        std::string op = t[0];
        t.erase(t.begin());
        RunOp(st, op, t);
        gOut += '\n';
    }
}

bool WriteAll(int fd, const char * p, size_t n)
{
    while (n)
    {
        ssize_t k = write(fd, p, n);
        if (k <= 0)
            return false;
        p += k;
        n -= static_cast<size_t>(k);
    }
    return true;
}

} // namespace

int main(int argc, char ** argv)
{
    if (argc < 2)
    {
        fprintf(stderr, "usage: %s <cases.txt> [--timeout S] [--only ID]\n", argv[0]);
        return 2;
    }
    int timeout = 10;
    std::string only;
    for (int i = 2; i + 1 < argc; i += 2)
    {
        if (!strcmp(argv[i], "--timeout"))
            timeout = atoi(argv[i + 1]);
        else if (!strcmp(argv[i], "--only"))
            only = argv[i + 1];
    }
    std::ifstream in(argv[1]);
    if (!in)
    {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    std::vector<Case> cases;
    std::string line;
    Case cur;
    bool inCase = false;
    while (std::getline(in, line))
    {
        if (line.rfind("CASE ", 0) == 0)
        {
            std::vector<std::string> t = Split(line);
            cur                        = Case{ t[1], t.size() > 2 ? t[2] : "x", {} };
            inCase                     = true;
        }
        else if (line == "END")
        {
            if (inCase && (only.empty() || only == cur.id))
                cases.push_back(cur);
            inCase = false;
        }
        else if (inCase)
            cur.ops.push_back(line);
    }
    signal(SIGPIPE, SIG_IGN);
    for (const Case & c : cases)
    {
        fflush(stdout);
        int fds[2];
        if (pipe(fds) != 0)
            return 3;
        pid_t pid = fork();
        if (pid < 0)
            return 3;
        if (pid == 0)
        {
            close(fds[0]);
            int devnull = open("/dev/null", O_WRONLY);
            if (devnull >= 0)
            {
                dup2(devnull, 1);
#ifndef CASE_RUNNER_NO_AS_LIMIT
                dup2(devnull, 2);
#endif
                close(devnull);
            }
#ifndef CASE_RUNNER_NO_AS_LIMIT
            struct rlimit rl = { 1024UL << 20, 1024UL << 20 };
            setrlimit(RLIMIT_AS, &rl);
#endif
            alarm(static_cast<unsigned>(timeout));
            RunCase(c);
            WriteAll(fds[1], gOut.data(), gOut.size());
            close(fds[1]);
            _exit(0);
        }
        close(fds[1]);
        std::string got;
        char buf[65536];
        ssize_t k;
        while ((k = read(fds[0], buf, sizeof buf)) > 0)
            got.append(buf, static_cast<size_t>(k));
        close(fds[0]);
        int status = 0;
        waitpid(pid, &status, 0);
        if (WIFEXITED(status) && WEXITSTATUS(status) == 0)
        {
            printf("C %s %s %zu\n", c.id.c_str(), c.bucket.c_str(), got.size());
            fwrite(got.data(), 1, got.size(), stdout);
        }
        else if (WIFSIGNALED(status))
            printf("X %s %s signal-%d\n", c.id.c_str(), c.bucket.c_str(), WTERMSIG(status));
        else
            printf("X %s %s exit-%d\n", c.id.c_str(), c.bucket.c_str(), WEXITSTATUS(status));
    }
    fflush(stdout);
    return 0;
}
