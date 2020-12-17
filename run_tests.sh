#!/bin/bash

echo "STARTING YORIC"

# Generate directory structure, chmods, etc.
SYNAPSE_SERVER_NAME=localhost:8008 SYNAPSE_REPORT_STATS=no /start.py generate

# Overwrite homeserver.yaml
cp test/homeserver.yaml ./homeserver.yaml

# Start matrix
/start.py
