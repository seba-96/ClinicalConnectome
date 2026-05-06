#!/bin/bash

# Update the path with the correct username
cd /home/sebacine/nextcloud
git clone https://github.com/seba-96/ClinicalConnectome.git
cd ClinicalConnectome
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .