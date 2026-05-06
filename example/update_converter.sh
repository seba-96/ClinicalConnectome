#!/bin/bash

cd nextcloud/ClinicalConnectome
git pull
source .venv/bin/activate
python -m pip install -e .