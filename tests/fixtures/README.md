# Local PDF fixtures

Place PDFs supplied for evaluation in this directory. PDF files here are
ignored by Git so test documents and their contents are not pushed to the
repository accidentally.

Tests that depend on the removed legacy fixtures are marked as ignored. When
new PDFs are added, create focused tests for the expected extraction behavior
and commit only those tests or redacted fixtures that are safe to publish.
