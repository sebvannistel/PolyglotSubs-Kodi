# Subget helper packaging

The real addon bundles platform-specific `subget` executables in
`resources/bin/<platform>/subget`. Binary payloads are not committed to
this repository, so the tree contains lightweight development stubs
instead. Packaging scripts **must** replace these shims with the actual
artifacts built from the `charleshuang3/subget` fork before shipping.

## Development stub checksums

| Platform | Path | SHA-256 |
| --- | --- | --- |
| Linux | `resources/bin/linux/subget` | `a01634898cc9640549f249ed0bc4a0a84f84838e414396ce3e7b0a594a248c52` |
| macOS | `resources/bin/macos/subget` | `71a4d8fea947f82bb2aea4b69f1cb99990a1de9e4f49de1250d070dbb610a843` |
| Android | `resources/bin/android/subget` | `3088656ddde94f8b3ca2e41b9e005481027128fc5f0d1ed43f2a8b6ded94c431` |
| Windows (batch shim) | `resources/bin/windows/subget.bat` | `21d1a8473b44ec5aee9999ae2933dbbb6a3b4783d228b637a3390da31ed16d97` |
| Windows (placeholder) | `resources/bin/windows/subget` | `7ccd60483e78b0393c3b4091de213745738662a5949e7498e6951be54cba680c` |

These hashes provide sanity checks during development so automated jobs
can detect when the real binaries were not injected.
