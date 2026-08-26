#include <H5Cpp.h>

#include <cstdio>
#include <iostream>

int main()
{
    const char *path = "hdf5-cxx-smoke.h5";
    const double expected[3] = {1.25, 2.5, 5.0};
    double actual[3] = {0.0, 0.0, 0.0};

    try {
        H5::Exception::dontPrint();
        {
            H5::H5File file(path, H5F_ACC_TRUNC);
            hsize_t dims[1] = {3};
            H5::DataSpace space(1, dims);
            H5::DataSet dataset = file.createDataSet("/values", H5::PredType::NATIVE_DOUBLE, space);
            dataset.write(expected, H5::PredType::NATIVE_DOUBLE);
        }
        {
            H5::H5File file(path, H5F_ACC_RDONLY);
            H5::DataSet dataset = file.openDataSet("/values");
            dataset.read(actual, H5::PredType::NATIVE_DOUBLE);
        }
    } catch (const H5::Exception &error) {
        std::cerr << "FAIL C++ HDF5: " << error.getDetailMsg() << '\n';
        return 1;
    }

    for (int i = 0; i < 3; ++i) {
        if (actual[i] != expected[i]) {
            std::cerr << "FAIL C++ HDF5: round-trip data mismatch\n";
            return 1;
        }
    }

    std::remove(path);
    std::cout << "PASS C++ HDF5" << std::endl;
    return 0;
}
