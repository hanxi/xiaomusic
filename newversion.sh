#!/bin/bash

cz bump --check-consistency --increment patch

git push -u origin main --tags
