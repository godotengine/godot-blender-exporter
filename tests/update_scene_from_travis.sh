#!/bin/bash

if [ -z "$1" ]
  then
    echo "Error: TravisCI job id is required."
fi

# These variable names should match the ones in .travis.yml
PATCH_BEGIN_LINE='cat tests_scenes_diff.patch'
PATCH_END_LINE='echo "scene diff path ends"'

JOB_ID=$1
RAW_LOG_URL=https://api.travis-ci.org/v3/job/${JOB_ID}/log.txt

REPO_ROOT=$(dirname $0)/..

cd $REPO_ROOT

PWD=$(pwd)
LOCAL_LOG_FILE=travis_${JOB_ID}_log.txt
GIT_PATCH_FILE=${JOB_ID}_scene_diff.patch

echo "Download travis build log from $RAW_LOG_URL"
echo "Store to $PWD/$LOCAL_LOG_FILE"
curl ${RAW_LOG_URL} --output $LOCAL_LOG_FILE

BEGIN_LINE_NUMBER=$(awk "/${PATCH_BEGIN_LINE}/{ print NR; exit }" $LOCAL_LOG_FILE)
END_LINE_NUMBER=$(awk "/${PATCH_END_LINE}/{ print NR; exit }" $LOCAL_LOG_FILE)
sed -n "$((${BEGIN_LINE_NUMBER} + 1)),$((${END_LINE_NUMBER} - 1))p" $LOCAL_LOG_FILE > $GIT_PATCH_FILE

git apply --verbose --ignore-whitespace --reject $GIT_PATCH_FILE 

rm $LOCAL_LOG_FILE
rm $GIT_PATCH_FILE

cd -
