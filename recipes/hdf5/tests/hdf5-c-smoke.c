#include <hdf5.h>
#include <hdf5_hl.h>

#include <stdio.h>
#include <stdlib.h>

static int fail(const char *message)
{
    fprintf(stderr, "FAIL C HDF5: %s\n", message);
    return 1;
}

int main(void)
{
    const char *path = "hdf5-c-smoke.h5";
    const hsize_t dims[2] = {2, 3};
    const int expected[6] = {1, 2, 3, 4, 5, 6};
    int actual[6] = {0};

    hid_t file = H5Fcreate(path, H5F_ACC_TRUNC, H5P_DEFAULT, H5P_DEFAULT);
    if (file < 0)
        return fail("H5Fcreate");
    if (H5LTmake_dataset(file, "/values", 2, dims, H5T_NATIVE_INT, expected) < 0)
        return fail("H5LTmake_dataset");
    if (H5Fclose(file) < 0)
        return fail("H5Fclose after write");

    file = H5Fopen(path, H5F_ACC_RDONLY, H5P_DEFAULT);
    if (file < 0)
        return fail("H5Fopen");
    hid_t dataset = H5Dopen2(file, "/values", H5P_DEFAULT);
    if (dataset < 0)
        return fail("H5Dopen2");
    if (H5Dread(dataset, H5T_NATIVE_INT, H5S_ALL, H5S_ALL, H5P_DEFAULT, actual) < 0)
        return fail("H5Dread");
    H5Dclose(dataset);
    H5Fclose(file);

    for (int i = 0; i < 6; ++i) {
        if (actual[i] != expected[i])
            return fail("round-trip data mismatch");
    }

    remove(path);
    puts("PASS C HDF5 base+HL");
    return 0;
}
