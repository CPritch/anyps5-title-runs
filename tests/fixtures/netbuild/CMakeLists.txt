# A build that reaches for the network at configure time (as a FetchContent or a download would): it downloads URL.
cmake_minimum_required(VERSION 3.20)
project(netbuild NONE)
file(DOWNLOAD "${URL}" "${CMAKE_BINARY_DIR}/downloaded" STATUS status TIMEOUT 10)
list(GET status 0 code)
if(NOT code EQUAL 0)
  message(FATAL_ERROR "download of ${URL} failed: ${status}")
endif()
message(STATUS "downloaded ${URL}")
