# External Helper Packaging

This addon expects platform-specific builds of the `subget` helper under
`resources/bin/<platform>/subget`. Binary artifacts are not tracked in this
repository – populate them during packaging or release automation.

## Expected layout

```
resources/
  bin/
    android/subget
    darwin/subget
    linux/subget
    windows/subget.exe
```

All helpers must be rebuilt from the `charleshuang3/subget` fork with the
JSON search and streaming download flags enabled. After placing the binaries,
record their checksums in the table below.

| Platform | Binary path | SHA256 checksum |
|----------|-------------|-----------------|
| Android  | `resources/bin/android/subget` | _fill during release_ |
| Darwin   | `resources/bin/darwin/subget`  | _fill during release_ |
| Linux    | `resources/bin/linux/subget`   | _fill during release_ |
| Windows  | `resources/bin/windows/subget.exe` | _fill during release_ |

Compute the hashes with:

```
sha256sum resources/bin/*/subget*
```

The release process should update this document with the resulting values.
