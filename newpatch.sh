#!/bin/bash

./update-static-version.py
./update-holiday.sh
git add xiaomusic/static
git commit -m 'build: update static version'
git pull --rebase

cz bump --check-consistency --increment patch

git push
git push --tags
