#!/bin/bash

if [ $# -ne 1 ]; then
	echo "Usage: $0 <yaml-file>"
	exit 1
fi

YAMLTREE_FILE=$1 python app.py

