set -ex
cd test
python3 -m unittest -v
mpiexec -n 2 python3 -m unittest -v
