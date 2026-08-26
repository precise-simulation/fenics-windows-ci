#include <mpi.h>
#include <hdf5.h>

#include <stdio.h>

static int fail(int rank, const char *message)
{
    fprintf(stderr, "FAIL MPI HDF5 rank=%d: %s\n", rank, message);
    MPI_Abort(MPI_COMM_WORLD, 1);
    return 1;
}

int main(int argc, char **argv)
{
    MPI_Init(&argc, &argv);

    int rank = 0;
    int size = 0;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);
    if (size < 2)
        return fail(rank, "requires at least two ranks");

    const char *path = "hdf5-mpi-smoke.h5";
    const hsize_t dims[1] = {(hsize_t)size};
    const hsize_t start[1] = {(hsize_t)rank};
    const hsize_t count[1] = {1};
    const int value = rank;
    int actual = -1;

    hid_t fapl = H5Pcreate(H5P_FILE_ACCESS);
    if (fapl < 0 || H5Pset_fapl_mpio(fapl, MPI_COMM_WORLD, MPI_INFO_NULL) < 0)
        return fail(rank, "MPI file-access property list");
    hid_t file = H5Fcreate(path, H5F_ACC_TRUNC, H5P_DEFAULT, fapl);
    H5Pclose(fapl);
    if (file < 0)
        return fail(rank, "H5Fcreate");

    hid_t filespace = H5Screate_simple(1, dims, NULL);
    hid_t dataset = H5Dcreate2(file, "/rank", H5T_NATIVE_INT, filespace,
                               H5P_DEFAULT, H5P_DEFAULT, H5P_DEFAULT);
    if (filespace < 0 || dataset < 0)
        return fail(rank, "dataset creation");

    hid_t memspace = H5Screate_simple(1, count, NULL);
    if (H5Sselect_hyperslab(filespace, H5S_SELECT_SET, start, NULL, count, NULL) < 0)
        return fail(rank, "hyperslab selection");
    hid_t dxpl = H5Pcreate(H5P_DATASET_XFER);
    if (dxpl < 0 || H5Pset_dxpl_mpio(dxpl, H5FD_MPIO_COLLECTIVE) < 0)
        return fail(rank, "collective transfer setup");
    if (H5Dwrite(dataset, H5T_NATIVE_INT, memspace, filespace, dxpl, &value) < 0)
        return fail(rank, "collective write");

    H5Pclose(dxpl);
    H5Sclose(memspace);
    H5Sclose(filespace);
    H5Dclose(dataset);
    H5Fclose(file);
    MPI_Barrier(MPI_COMM_WORLD);

    fapl = H5Pcreate(H5P_FILE_ACCESS);
    if (fapl < 0 || H5Pset_fapl_mpio(fapl, MPI_COMM_WORLD, MPI_INFO_NULL) < 0)
        return fail(rank, "MPI reopen property list");
    file = H5Fopen(path, H5F_ACC_RDONLY, fapl);
    H5Pclose(fapl);
    if (file < 0)
        return fail(rank, "H5Fopen");
    dataset = H5Dopen2(file, "/rank", H5P_DEFAULT);
    filespace = H5Dget_space(dataset);
    memspace = H5Screate_simple(1, count, NULL);
    if (H5Sselect_hyperslab(filespace, H5S_SELECT_SET, start, NULL, count, NULL) < 0)
        return fail(rank, "read hyperslab selection");
    if (H5Dread(dataset, H5T_NATIVE_INT, memspace, filespace, H5P_DEFAULT, &actual) < 0)
        return fail(rank, "read");

    H5Sclose(memspace);
    H5Sclose(filespace);
    H5Dclose(dataset);
    H5Fclose(file);
    if (actual != value)
        return fail(rank, "rank data mismatch");

    MPI_Barrier(MPI_COMM_WORLD);
    if (rank == 0)
        remove(path);
    MPI_Finalize();
    if (rank == 0)
        puts("PASS MPI HDF5 collective 2+ ranks");
    return 0;
}
