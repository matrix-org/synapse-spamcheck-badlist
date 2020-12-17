FROM matrixdotorg/synapse:latest

# Install extension.
WORKDIR /data
COPY . .
COPY run_tests.sh .
RUN pip install .

# Run
ENTRYPOINT ["./run_tests.sh"]


