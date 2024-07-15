#!/bin/bash

./update-static-version.py
git add xiaomusic/static
git commit -m 'build: update static version'

cz bump --check-consistency --increment patch

git push -u origin main --tags
