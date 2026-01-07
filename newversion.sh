#!/bin/bash

./update-static-version.py
./update-holiday.sh
git add xiaomusic/static
git commit -m 'build: update static version'
git pull origin main --rebase

cz bump --check-consistency

git push -u origin main --tags
