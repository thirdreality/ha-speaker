cmake_minimum_required(VERSION 3.16)
project(sendspin-client VERSION 1.0.0 LANGUAGES CXX)

# Build sendspin-cpp as a subdirectory
add_subdirectory(sendspin-cpp EXCLUDE_FROM_ALL)

# Build our PulseAudio client
add_executable(sendspin-client sendspin-client.cpp)
target_link_libraries(sendspin-client PRIVATE sendspin)
target_compile_features(sendspin-client PRIVATE cxx_std_20)

# PulseAudio
find_package(PkgConfig REQUIRED)
pkg_check_modules(PULSE REQUIRED libpulse-simple)
target_include_directories(sendspin-client PRIVATE ${PULSE_INCLUDE_DIRS})
target_link_libraries(sendspin-client PRIVATE ${PULSE_LIBRARIES})

install(TARGETS sendspin-client RUNTIME DESTINATION bin)
