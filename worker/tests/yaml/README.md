Sample player YAMLs for the `validate-yaml` job. These need a real Archipelago, so they run
in `docker/smoke-test.sh` against the built image, not in pytest. Each file name starts with
the expected result: `ok` or the error code of the first document that should fail.
