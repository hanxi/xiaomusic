#!/bin/bash

./update-static-version.py
cz bump --check-consistency --increment patch

git push -u origin main --tags
