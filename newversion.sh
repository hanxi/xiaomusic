#!/bin/bash

./update-static-version.py
./update-holiday.sh
git add xiaomusic/static
git commit -m 'build: update static version'

cz bump --check-consistency

git push -u origin main --tags
