"""Assemble the trimmed connectedhomeip v1.6.1.0 tree.

usage: python3 -I make_tree.py <clone> <out> [--closure deps.txt]
Copies the library sources (SOURCES), the overlay (CMakeLists.txt, shim/), the licence files and headers:
every header under the include roots, or only those listed in deps.txt (the header closure of a build).
"""
import os, shutil, sys

clone, out = sys.argv[1], sys.argv[2]
closure = None
if len(sys.argv) > 4 and sys.argv[3] == "--closure":
    closure = set(l.strip() for l in open(sys.argv[4]) if l.strip())

SOURCES = """
src/lib/core/CHIPError.cpp src/lib/core/ErrorStr.cpp
src/lib/core/TLVCircularBuffer.cpp src/lib/core/TLVDebug.cpp src/lib/core/TLVReader.cpp src/lib/core/TLVTags.cpp
src/lib/core/TLVUpdater.cpp src/lib/core/TLVUtilities.cpp src/lib/core/TLVVectorWriter.cpp src/lib/core/TLVWriter.cpp
src/transport/raw/MessageHeader.cpp
src/setup_payload/Base38Encode.cpp src/setup_payload/Base38Decode.cpp
src/setup_payload/ManualSetupPayloadGenerator.cpp src/setup_payload/ManualSetupPayloadParser.cpp
src/setup_payload/QRCodeSetupPayloadGenerator.cpp src/setup_payload/QRCodeSetupPayloadParser.cpp
src/setup_payload/SetupPayload.cpp src/setup_payload/AdditionalDataPayloadParser.cpp
src/lib/support/jsontlv/TlvJson.cpp src/lib/support/jsontlv/TlvToJson.cpp src/lib/support/jsontlv/JsonToTlv.cpp
src/lib/support/jsontlv/TextFormat.cpp
src/lib/support/Base64.cpp src/lib/support/BufferReader.cpp src/lib/support/BufferWriter.cpp
src/lib/support/BytesToHex.cpp src/lib/support/CHIPMem.cpp src/lib/support/CHIPMem-Malloc.cpp
src/lib/support/StringBuilder.cpp src/lib/support/utf8.cpp src/lib/support/logging/TextOnlyLogging.cpp
src/lib/support/verhoeff/Verhoeff.cpp src/lib/support/verhoeff/Verhoeff10.cpp
src/system/SystemPacketBuffer.cpp src/system/SystemError.cpp
""".split()
EXTRA = ["LICENSE", "NOTICE", "src/lib/support/jsontlv/README.md",
         "third_party/nlassert/repo/LICENSE", "third_party/nlio/repo/LICENSE"]
INC_ROOTS = ["src", "config/standalone", "third_party/nlassert/repo/include", "third_party/nlio/repo/include"]
HDR = (".h", ".hpp", ".ipp", ".inc", ".def")

def cp(rel):
    s, d = os.path.join(clone, rel), os.path.join(out, rel)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copy2(s, d)

if os.path.exists(out):
    shutil.rmtree(out)
for rel in SOURCES + [e for e in EXTRA if os.path.exists(os.path.join(clone, e))]:
    cp(rel)
if closure is not None:
    for rel in sorted(closure):
        cp(rel)
else:
    for root in INC_ROOTS:
        for dp, dn, fn in os.walk(os.path.join(clone, root)):
            dn[:] = [d for d in dn if d not in ("tests", ".git")]
            for n in fn:
                if n.endswith(HDR):
                    cp(os.path.relpath(os.path.join(dp, n), clone))
here = os.path.dirname(os.path.abspath(__file__))
shutil.copy2(os.path.join(here, "overlay", "CMakeLists.txt"), out)
shutil.copytree(os.path.join(here, "overlay", "shim"), os.path.join(out, "shim"))
print("tree at", out)
