# A Dockerfile used for running tests.
# This Dockerfile should work for other plug-ins, too.

FROM matrixdotorg/synapse:latest

# Install extension.
WORKDIR /data
COPY . .
RUN pip install .

RUN apt-get update --quiet && apt-get install postgresql-client --yes --quiet

# Run
#ENTRYPOINT ["tail", "-f", "/data/test/run_tests.sh"]
ENTRYPOINT ["/data/test/run_tests.sh"]


