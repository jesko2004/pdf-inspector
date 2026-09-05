# Publishing

This repository is maintained and released as `jesko2004/pdf-inspector`.

The planned distribution names are:

- Rust crate: `jesko-pdf-inspector`
- Python distribution: `jesko-pdf-inspector`
- Node.js package: `@jesko2004/pdf-inspector`
- Browser package: `@jesko2004/pdf-inspector-wasm`

The publishing workflows are manual-only and run from `main`. Before the first
release, configure trusted publishing for this repository in crates.io, PyPI,
and npm. The `jesko2004` npm scope must be owned by the publishing account.

## Release steps

1. Update the version in the corresponding manifest.
2. Run the local format, lint, test, and release-build checks.
3. Merge the reviewed version change into `main`.
4. Run the matching publishing workflow manually.
5. Verify the package metadata and installation instructions after publication.

The copyright notice included with the MIT license remains in `LICENSE` and
`wasm/LICENSE` as required by that license.
