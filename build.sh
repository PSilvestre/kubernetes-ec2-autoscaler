#!/bin/sh
mkdir build
cp main.py build/
cp -r autoscaler/ build/
cp -r data/ build/
cp requirements.txt build/
cp production-requirements.txt build/
cp setup.py build/
cp Dockerfile build/
cd build/ && docker build -q -t psylvan/baremetal-autoscaler . && docker push psylvan/baremetal-autoscaler
