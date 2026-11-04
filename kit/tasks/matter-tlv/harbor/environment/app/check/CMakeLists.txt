# Builds case_runner against the chipcore library of the tree given as -DTREE=<path>.
cmake_minimum_required(VERSION 3.20)
project(case_runner CXX)
add_subdirectory(${TREE} chipcore)
add_executable(case_runner case_runner.cpp)
target_link_libraries(case_runner PRIVATE chipcore)
