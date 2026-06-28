cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# Project configuration
set(PROJECT_VER "1.0.0")
set(PROJECT_NAME "pulsescope")

project(${PROJECT_NAME} VERSION ${PROJECT_VER})

# Component directories
set(EXTRA_COMPONENT_DIRS ${CMAKE_CURRENT_LIST_DIR}/components)

# Default build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Compiler flags
target_compile_options(${PROJECT_NAME}.elf PRIVATE
    -Wall -Wextra -Wpedantic
    -Wno-unused-parameter
    -Wno-missing-field-initializers
    -std=gnu++17
)

# Linker flags for size optimization
target_link_options(${PROJECT_NAME}.elf PRIVATE
    -Wl,--gc-sections
)

# Partition table
set(PARTITION_TABLE_CUSTOM_FILENAME ${CMAKE_CURRENT_LIST_DIR}/partitions.csv)