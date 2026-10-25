#!/bin/sh
set -eu
cd /workdir
python3 -c 'from program_artifact import verify; verify("/program", "build")'
mkdir -p core/generated
cp -R /program/. core/generated/
exec bash ./start_openplc.sh
