#!/bin/bash

if [ -d buildroot/dl ]; then
    mv buildroot/dl ./
fi

rm buildroot -rf

repo sync buildroot

if [ -d dl ]; then
    mv dl ./buildroot
fi
