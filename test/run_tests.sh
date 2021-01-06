#!/bin/bash

cd /data

# 1. Configuring Synapse
echo TESTER: Configuring Synapse

## 1a. Generate directory structure, chmods, etc.
SYNAPSE_SERVER_NAME="localhost:8080" SYNAPSE_REPORT_STATS=no /start.py generate

## 1b. Overwrite configuration
cp /data/test/config/homeserver.yaml /data/homeserver.yaml
cp /data/test/config/localhost:8080.log.config /data/localhost:8080.log.config

## 1c. Create database
echo *:*:*:postgres:postgres > ~/.pgpass
chmod 0600 ~/.pgpass
psql --quiet --user postgres --host=postgres --file /data/test/1_create_database.sql

# 2. Launching Synapse
echo TESTER: Launching Synapse
synctl start

# 3. Setting up test
## 3a. Installing dependencies for the test.
pip install --quiet requests

## 3b. Create test-specific schema and tables
echo TESTER: Setting up schema and tables
psql postgres --quiet --user postgres --host=postgres --file /data/test/2_create_schema_and_tables.sql
psql postgres --quiet --user postgres --host=postgres --file /data/test/3_insert_evil_data.sql

## 3c. Create users
echo TESTER: Registering users
register_new_matrix_user -c /data/homeserver.yaml -u user_1 -p user_1 --no-admin http://localhost:8080
register_new_matrix_user -c /data/homeserver.yaml -u user_2 -p user_2 --no-admin http://localhost:8080

# 4. Running test
echo TESTER: Running test
python /data/test/4_test.py
RESULT=$?

# 5. In case of failure, display logs
if [[ $RESULT != 0 ]]; then
    echo TESTER: Test failed, displaying logs
    cat /data/*.log
    exit 1
fi

echo TESTER: Tests successful!
exit 0
