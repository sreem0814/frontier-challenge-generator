# Trimmed build of connectedhomeip v1.6.1.0: the TLV codec (src/lib/core), message framing
# (src/transport/raw), setup payload codecs (src/setup_payload) and JSON<->TLV (src/lib/support/jsontlv),
# plus the support code they need, as one static library: build/libchipcore.a.
# Every .cpp file in the four component directories is compiled, so new files there are picked up.
cmake_minimum_required(VERSION 3.20)
project(chipcore CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

find_package(PkgConfig REQUIRED)
pkg_check_modules(JSONCPP REQUIRED jsoncpp)

set(R ${CMAKE_CURRENT_SOURCE_DIR})
file(GLOB COMPONENT_SRC CONFIGURE_DEPENDS
  ${R}/src/lib/core/*.cpp
  ${R}/src/transport/raw/*.cpp
  ${R}/src/setup_payload/*.cpp
  ${R}/src/lib/support/jsontlv/*.cpp)

set(SUPPORT_SRC
  ${R}/src/lib/support/Base64.cpp
  ${R}/src/lib/support/BufferReader.cpp
  ${R}/src/lib/support/BufferWriter.cpp
  ${R}/src/lib/support/BytesToHex.cpp
  ${R}/src/lib/support/CHIPMem.cpp
  ${R}/src/lib/support/CHIPMem-Malloc.cpp
  ${R}/src/lib/support/StringBuilder.cpp
  ${R}/src/lib/support/utf8.cpp
  ${R}/src/lib/support/logging/TextOnlyLogging.cpp
  ${R}/src/lib/support/verhoeff/Verhoeff.cpp
  ${R}/src/lib/support/verhoeff/Verhoeff10.cpp
  ${R}/src/system/SystemPacketBuffer.cpp
  ${R}/src/system/SystemError.cpp
  ${R}/shim/PlatformShim.cpp)

add_library(chipcore STATIC ${COMPONENT_SRC} ${SUPPORT_SRC})
target_include_directories(chipcore PUBLIC
  ${R}/src ${R}/src/include ${R}/src/platform/Linux ${R}/config/standalone ${R}/shim/include
  ${R}/third_party/nlassert/repo/include ${R}/third_party/nlio/repo/include ${JSONCPP_INCLUDE_DIRS})
target_compile_definitions(chipcore PUBLIC
  CHIP_HAVE_CONFIG_H=0
  CHIP_SYSTEM_CONFIG_USE_SOCKETS=1 CHIP_SYSTEM_CONFIG_USE_POSIX_SOCKETS=1 CHIP_SYSTEM_CONFIG_USE_LWIP=0
  HAVE_CLOCK_GETTIME=1 CHIP_SYSTEM_CONFIG_USE_POSIX_TIME_FUNCTS=1 CHIP_SYSTEM_CONFIG_POSIX_LOCKING=1
  CHIP_SYSTEM_CONFIG_USE_DISPATCH=0 CHIP_DEVICE_LAYER_TARGET=Linux CHIP_DEVICE_LAYER_TARGET_LINUX=1
  CHIP_CONFIG_MEMORY_MGMT_MALLOC=1 CHIP_ERROR_LOGGING=0 CHIP_PROGRESS_LOGGING=0 CHIP_DETAIL_LOGGING=0
  CHIP_CONFIG_TLV_VALIDATE_CHAR_STRING_ON_WRITE=1 CHIP_SYSTEM_CONFIG_PACKETBUFFER_POOL_SIZE=0
  "CHIP_PROJECT_CONFIG_INCLUDE=<CHIPProjectConfig.h>"
  "CHIP_SYSTEM_PROJECT_CONFIG_INCLUDE=<SystemProjectConfig.h>"
  "CHIP_PLATFORM_CONFIG_INCLUDE=<platform/Linux/CHIPPlatformConfig.h>"
  "CHIP_SYSTEM_CONFIG_INCLUDE=<platform/Linux/SystemPlatformConfig.h>"
  "INET_CONFIG_INCLUDE=<platform/Linux/InetPlatformConfig.h>")
target_link_libraries(chipcore PUBLIC ${JSONCPP_LIBRARIES})
