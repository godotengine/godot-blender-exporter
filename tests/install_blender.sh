#!/bin/sh

set -e

BLENDER_28_LINUX_64_URL="https://mirror.clarkson.edu/blender/release/Blender2.80/blender-2.80-linux-glibc217-x86_64.tar.bz2"

BLENDER_DIRNAME_REGEX_PATTERN='/Blender2\.80/(.+)\.tar\.bz2$'
[[ ${BLENDER_28_LINUX_64_URL} =~ ${BLENDER_DIRNAME_REGEX_PATTERN} ]]
NAME=${BASH_REMATCH[1]}

VERSION=2.80
CACHE="${HOME}/.blender-cache"
TAR="${CACHE}/${NAME}.tar.bz2"

echo "Installing Blender ${VERSION}"
mkdir -p $CACHE
if [ ! -f $TAR ]; then
    wget -O $TAR $BLENDER_28_LINUX_64_URL
fi
tar -xjf $TAR -C $HOME

echo "export BLENDER_BIN=\"${HOME}/${NAME}/blender\"" > .envs
