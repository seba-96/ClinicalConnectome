#!/bin/bash

# Update the path with the correct username
cd /home/sebacine/nextcloud/ClinicalConnectome
git pull
source .venv/bin/activate
python -m pip install -e .