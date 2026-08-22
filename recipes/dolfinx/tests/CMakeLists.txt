cmake_minimum_required(VERSION 3.26)
project(dolfinx_petsc_consumer LANGUAGES CXX)

find_package(DOLFINX CONFIG REQUIRED)

if(NOT TARGET PkgConfig::PETSC)
  message(FATAL_ERROR "Installed DOLFINx configuration did not load PETSc")
endif()

get_target_property(DOLFINX_DEFINITIONS dolfinx INTERFACE_COMPILE_DEFINITIONS)
if(NOT "HAS_PETSC" IN_LIST DOLFINX_DEFINITIONS)
  message(FATAL_ERROR "Installed DOLFINx target does not report HAS_PETSC")
endif()

add_executable(dolfinx-petsc-consumer main.cpp)
target_link_libraries(dolfinx-petsc-consumer PRIVATE dolfinx)
