// Platform pieces the trimmed build needs and the full SDK gets from its platform layer:
// a no-op log sink and a DRBG backed by /dev/urandom (only SetupPayload::generateRandomSetupPin uses it).
#include <crypto/CHIPCryptoPAL.h>
#include <lib/support/logging/CHIPLogging.h>
#include <cstdio>

namespace chip {
namespace Logging {
namespace Platform {
void LogV(const char *, uint8_t, const char *, va_list) {}
} // namespace Platform
} // namespace Logging
namespace Crypto {
CHIP_ERROR DRBG_get_bytes(uint8_t * out_buffer, size_t out_length)
{
    FILE * f = fopen("/dev/urandom", "rb");
    if (f == nullptr)
        return CHIP_ERROR_INTERNAL;
    size_t n = fread(out_buffer, 1, out_length, f);
    fclose(f);
    return n == out_length ? CHIP_NO_ERROR : CHIP_ERROR_INTERNAL;
}
} // namespace Crypto
} // namespace chip
