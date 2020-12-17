#!/bin/bash

# Build a Docker image for the `develop` branch of Synapse

\rm -Rf synapse
git clone git@github.com:matrix-org/synapse.git synapse
docker build -t matrixdotorg/synapse -f synapse/docker/Dockerfile synapse
