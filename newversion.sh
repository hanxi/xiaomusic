#!/bin/bash

./update-static-version.py
cz bump --check-consistency

git push -u origin main --tags
