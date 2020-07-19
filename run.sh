#!/bin/bash


cd `dirname "$0"`
source setup.sh

python measure.py >> log.log 2>&1 

