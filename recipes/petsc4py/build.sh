#!/bin/sh
set -ex
${PYTHON} conf/cythonize.py
${PYTHON} -m pip -v install --no-deps .
