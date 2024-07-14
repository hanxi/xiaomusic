#!/bin/bash

cz bump --check-consistency

git push -u origin main --tags
