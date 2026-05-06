#!/bin/bash

# Update the paths with the correct username
cd /home/sebacine/nextcloud/ClinicalConnectome
source .venv/bin/activate

bids-converter /home/sebacine/nextcloud/Clinical_connectome/UNIPD/WashU /home/sebacine/nextcloud/Clinical_connectome_bids/UNIPD/WashU \
--lesion-space MNI152NLin6Asym


