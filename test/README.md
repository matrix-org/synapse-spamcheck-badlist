# About these tests

Running integration tests on a plug-in requires a fairly large harness, but this harness should be mostly reusable
for other plug-ins.

Here is how it works and how it could be customized.

## Running the tests

Use the following steps to run tests locally.

```sh
# Prepare the latest Synapse docker image (slow, you don't need to do it often)
$ ./test/before_test.sh
$ docker-compose down --remove-orphans
# Purge any previous version of the test, otherwise `docker-compose` ignores changes.
$ docker container prune
# Launch the test
$ docker-compose up --build --abort-on-container-exit
```
For CI testing, you probably wish to integrate the following steps in your BuildKit pipeline, your `.travis.yml`, your `.gitlab-ci.yml`, etc.

## What happens when you run `docker-compose up --build`

1. Starting from the Synapse docker image we just built
    a. Install `psql` (we'll need to add stuff to the database).
    b. Install the plug-in we wish to test.
    c. Run `test/run_tests.sh`
2. In `run_test.sh`
    1. Configure Synapse
        a. Launch `generate` to generate directory structure, perform proper chmods, etc.
        b. Overwrite the configuration
            - Use `test/config/homeserver.yaml` to configure the database and the plug-in.
                - **If you wish to test another plug-in, you will need to tweak this file to launch your plug-in instead of this one.**
            - Use `test/config/localhost:8080.log.config`, to ensure that we can access the logs.
        c. Create the database from `test/1_create_database.sql`, as required to launch Synapse
    2. Launch Synapse in the background.
    3. Setup the test
        a. The test is written in Python. We need to ensure that any dependencies are installed.
            - **If you have additional dependencies, add them here.**
        b. Add test-specific changes to the database as needed from `test/2_create_schema_and_tables.sql` and `test/3_insert_evil_data.sql`
            - **If your test needs any SQL manipulation, this is where you should do it.**
        c. Register a few users.
    4. Switch to Python to launch the actual test from `test/4_test.py`.
        - Logs are redirected to `/data/test.log` to avoid displaying unneeded output.
        - **You probably wish to replace `test/4_test.py` is with your actual test.**
    5. In case of failure, display the logs.
    6. Exit and propagate test result.
3. If the test result is a failure, this will register as a non-0 result and show up as a failure in your CI.
