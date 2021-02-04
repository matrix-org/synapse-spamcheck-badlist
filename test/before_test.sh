#!/bin/bash

# Build a Docker image for the `develop` branch of Synapse

\rm -Rf synapse
git clone https://github.com/matrix-org/synapse.git
cd synapse
git checkout erikj/media_spam_checker
cd ..
docker build -t matrixdotorg/synapse -f synapse/docker/Dockerfile synapse
