cmake_minimum_required(VERSION 3.16)
project(RakSAMP CXX C)

# Headless Linux port of the RakSAMP 0.3.7 client (SA-MP bot).
# The original Win32 build is still available via RakSAMP_2008.sln on Windows.

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED OFF)
set(CMAKE_CXX_EXTENSIONS ON)

# The exact source set the Windows client links (from RakSAMPClient_2008.vcxproj),
# plus the Linux GUI stub.
set(RAKSAMP_SOURCES
    common/common.cpp
    raknet/AsynchronousFileIO.cpp
    raknet/BitStream.cpp
    raknet/BitStream_NoTemplate.cpp
    raknet/CheckSum.cpp
    raknet/DS_ByteQueue.cpp
    raknet/DS_HuffmanEncodingTree.cpp
    raknet/DS_Table.cpp
    raknet/DataBlockEncryptor.cpp
    raknet/DataCompressor.cpp
    raknet/EncodeClassName.cpp
    raknet/GetTime.cpp
    raknet/InternalPacketPool.cpp
    raknet/LinuxStrings.cpp
    raknet/NetworkIDGenerator.cpp
    raknet/NetworkTypes.cpp
    raknet/PluginInterface.cpp
    raknet/RPCMap.cpp
    raknet/RakClient.cpp
    raknet/RakNetStatistics.cpp
    raknet/RakNetworkFactory.cpp
    raknet/RakPeer.cpp
    raknet/RakSleep.cpp
    raknet/Rand.cpp
    raknet/ReliabilityLayer.cpp
    raknet/SAMP/SAMPRPC.cpp
    raknet/SAMP/samp_auth.cpp
    raknet/SAMP/samp_netencr.cpp
    raknet/SHA1.cpp
    raknet/SimpleMutex.cpp
    raknet/SocketLayer.cpp
    raknet/StringCompressor.cpp
    raknet/StringTable.cpp
    raknet/SystemAddressList.cpp
    raknet/TableSerializer.cpp
    raknet/_findfirst.cpp
    raknet/rakserver.cpp
    raknet/rijndael.cpp
    tinyxml/tinystr.cpp
    tinyxml/tinyxml.cpp
    tinyxml/tinyxmlerror.cpp
    tinyxml/tinyxmlparser.cpp
    client/src/cmds.cpp
    client/src/console.cpp
    client/src/localplayer.cpp
    client/src/main.cpp
    client/src/math_stuff.cpp
    client/src/misc_funcs.cpp
    client/src/netgame.cpp
    client/src/netrpc.cpp
    client/src/rcon.cpp
    client/src/window.cpp
    client/src/xmlsets.cpp
)

if(NOT WIN32)
    list(APPEND RAKSAMP_SOURCES client/src/window_linux.cpp)
endif()

add_executable(raksamp ${RAKSAMP_SOURCES})

target_include_directories(raksamp PRIVATE
    client/src
    common
    raknet
    raknet/SAMP
    tinyxml
)

# RAKSAMP_CLIENT gates the client-side SAMP netcode in RakPeer (matches the vcxproj).
# _RAKNET_THREADSAFE enables RakNet's mutexes: the stdin control thread and the
# network loop both touch pRakClient concurrently.
target_compile_definitions(raksamp PRIVATE RAKSAMP_CLIENT _RAKNET_THREADSAFE)

if(WIN32)
    target_link_libraries(raksamp PRIVATE ws2_32 winmm)
    target_compile_definitions(raksamp PRIVATE _CRT_SECURE_NO_WARNINGS)
else()
    # Legacy code: string-literal -> char*, old narrowing, etc. Keep it building
    # without drowning in warnings; real errors still fail the build.
    target_compile_options(raksamp PRIVATE -fpermissive -w -O2)
    find_package(Threads REQUIRED)
    target_link_libraries(raksamp PRIVATE Threads::Threads)
    # clock_gettime lives in librt on older glibc; harmless when it is in libc.
    target_link_libraries(raksamp PRIVATE rt)
    # Static C++/gcc runtime so the binary only needs glibc in the slim runtime image.
    target_link_options(raksamp PRIVATE -static-libstdc++ -static-libgcc)
endif()

set_target_properties(raksamp PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
