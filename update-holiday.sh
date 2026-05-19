#!/bin/bash

rm -rf holiday-cn
git clone https://github.com/NateScarlet/holiday-cn.git
mkdir -p holiday
cp holiday-cn/*.json holiday/
rm -rf holiday-cn
