cmake_minimum_required(VERSION 3.26)
project(hdf5_consumer_smoke LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(HDF5 CONFIG REQUIRED COMPONENTS C CXX HL CXX_HL)
find_package(MPI REQUIRED COMPONENTS C)

add_executable(hdf5-c-smoke hdf5-c-smoke.c)
target_link_libraries(hdf5-c-smoke PRIVATE hdf5_hl-shared hdf5-shared)

add_executable(hdf5-cxx-smoke hdf5-cxx-smoke.cpp)
target_link_libraries(hdf5-cxx-smoke PRIVATE hdf5_cpp-shared)

add_executable(hdf5-mpi-smoke hdf5-mpi-smoke.c)
target_link_libraries(hdf5-mpi-smoke PRIVATE hdf5-shared MPI::MPI_C)
