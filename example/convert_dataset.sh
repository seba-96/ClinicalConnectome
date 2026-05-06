#!/bin/bash

cd nextcloud
source ClinicalConnectome/.venv/bin/activate

# Update the paths with the correct center and dataset name
bids-converter Clinical_connectome/UNIPD/WashU Clinical_connectome_bids/UNIPD/WashU


