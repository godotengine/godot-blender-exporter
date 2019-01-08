#!/bin/sh

set -e

# hack, may be removed after find a stable blender2.8 build
BLENDER_ORG_HOMEPAGE="https://builder.blender.org"
DOWNLOAD_PAGE_HTML="`wget -qO- ${BLENDER_ORG_HOMEPAGE}/download`"
DAILY_BUILD_REGEX_PATTERN='href="([^"]+)" title="Download Dev Linux 64 bit master"'
[[ ${DOWNLOAD_PAGE_HTML} =~ ${DAILY_BUILD_REGEX_PATTERN} ]]
BLENDER_28_LINUX_64_PATH=${BASH_REMATCH[1]}

BLENDER_DIRNAME_REGEX_PATTERN='/download/(.+)\.tar\.bz2$'
[[ ${BLENDER_28_LINUX_64_PATH} =~ ${BLENDER_DIRNAME_REGEX_PATTERN} ]]
NAME=${BASH_REMATCH[1]}

VERSION=2.80
CACHE="${HOME}/.blender-cache"
TAR="${CACHE}/${NAME}.tar.bz2"
URL="${BLENDER_ORG_HOMEPAGE}/${BLENDER_28_LINUX_64_PATH}"

echo "Installing Blender ${VERSION}"
mkdir -p $CACHE
if [ ! -f $TAR ]; then
    wget -O $TAR $URL
fi
tar -xjf $TAR -C $HOME

echo "export BLENDER_BIN=\"${HOME}/${NAME}/blender\"" > .envs
