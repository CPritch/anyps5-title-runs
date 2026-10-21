cmake_minimum_required(VERSION 3.20)
project(hello CXX)
add_executable(hello hello.cpp)
add_custom_target(libs DEPENDS hello)
