Sample apworlds for the `test-apworld` job, used by `docker/smoke-test.sh`.

Each folder is `<expected>__<module>`: its contents are zipped into `<module>/` of
`<module>.apworld`. Expected results: `loaded`, `replaces` (loads, and replaces a built-in
world), `failed`. They are written for these tests and contain no game code.
