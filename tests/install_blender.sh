#!/bin/sh

set -e

BLENDER_VERSION=$1

BLENDER_LINUX_64_URL="https://mirror.clarkson.edu/blender/release/Blender${BLENDER_VERSION}/blender-${BLENDER_VERSION}-linux-glibc217-x86_64.tar.bz2"

BLENDER_DIRNAME_REGEX_PATTERN='/Blender2\.[0-9]+/(.+)\.tar\.bz2$'
[[ ${BLENDER_LINUX_64_URL} =~ ${BLENDER_DIRNAME_REGEX_PATTERN} ]]
NAME=${BASH_REMATCH[1]}

CACHE="${HOME}/.blender-cache"
TAR="${CACHE}/${NAME}.tar.bz2"

echo "Installing Blender ${BLENDER_VERSION}"
mkdir -p $CACHE
if [ ! -f $TAR ]; then
    wget -O $TAR $BLENDER_LINUX_64_URL
fi
tar -xjf $TAR -C $HOME

echo "export BLENDER_BIN=\"${HOME}/${NAME}/blender\"" > .envs
