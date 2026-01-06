#!/bin/bash

./update-static-version.py
./update-holiday.sh
git add xiaomusic/static
git commit -m 'build: update static version'
git push -u origin main

cz bump --check-consistency

git push -u origin main --tags
