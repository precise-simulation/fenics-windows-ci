cmake_minimum_required(VERSION 3.15)
project(petsc_windows_test LANGUAGES C)

find_package(PkgConfig REQUIRED)
pkg_check_modules(PETSC REQUIRED IMPORTED_TARGET PETSc)

add_executable(ex1 ex1.c)
target_link_libraries(ex1 PRIVATE PkgConfig::PETSC)
