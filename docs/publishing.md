# Publishing

This repository is maintained at `jesko2004/pdf-inspector`. The package names
on crates.io, PyPI, and the `@firecrawl` npm scope belong to the upstream
project and are kept in installation examples only as compatible upstream
releases.

The inherited publishing workflows are manual-only. Do not run them until
independent package names have been selected and registry trusted publishing
has been configured for `jesko2004/pdf-inspector`.

Before enabling automated releases:

1. Select available package names for crates.io, PyPI, npm, and WebAssembly.
2. Update the package manifests, generated package names, optional native
   dependencies, and installation documentation together.
3. Configure each registry's trusted publisher for this repository and its
   corresponding workflow.
4. Verify package contents with the workflow's dry-run step.
5. Restore the version-change `push` trigger only after the first independent
   release succeeds.

The original Firecrawl copyright notices remain in `LICENSE` and
`wasm/LICENSE` as required by the MIT license.
