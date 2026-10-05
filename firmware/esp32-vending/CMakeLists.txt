cmake_minimum_required(VERSION 3.16)

# Include ESP-IDF build system
include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# Register common firmware component path
set(EXTRA_COMPONENT_DIRS "../common")

project(esp32-vending-firmware)
