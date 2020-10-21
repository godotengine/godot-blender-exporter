#!/bin/bash

set -e

BLENDER_VERSION=$1
# https://download.blender.org/source/blender-2.90.1.tar.xz
BLENDER_LINUX_64_URL="https://download.blender.org/release/Blender2.90/blender-2.90.1-linux64.tar.xz"
BLENDER_DIRNAME_REGEX_PATTERN='/blender-2\.[0-9]+(\.[0-9]+)?-(.+)\.tar\.xz$'
[[ ${BLENDER_LINUX_64_URL} =~ ${BLENDER_DIRNAME_REGEX_PATTERN} ]]
echo $BLENDER_DIRNAME_REGEX_PATTERN
NAME=${BASH_REMATCH[0]%".tar.xz"}

CACHE="${HOME}/.blender-cache"
TAR="${CACHE}/${NAME}.tar.xz"

echo "Installing Blender ${BLENDER_VERSION}"
mkdir -p $CACHE
if [ ! -f $TAR ]; then
    wget -O $TAR $BLENDER_LINUX_64_URL
fi
tar -xvf $TAR -C $HOME

echo "export BLENDER_BIN=\"${HOME}/${NAME}/blender\"" > .envs
