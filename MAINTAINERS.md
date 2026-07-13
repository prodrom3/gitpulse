# Maintainers

## Primary maintainer

- **prodrom3** - [github.com/prodrom3](https://github.com/prodrom3)
  - Scope: all code, releases, security response
  - Response SLO (best effort, no commercial commitment): bug reports within 2 weeks, security reports within 72 hours

## Organization

- **radamic** - owning organization and copyright holder for the MIT license

## Escalation path

1. **Bugs, feature requests:** open a GitHub issue at https://github.com/prodrom3/nostos/issues
2. **Security issues:** follow the private disclosure process in [SECURITY.md](.github/SECURITY.md). Do not file public issues for vulnerabilities.
3. **Merge conflicts or build infrastructure:** mention the primary maintainer on the relevant PR or issue.

## Release authority

- Only the primary maintainer tags releases and publishes to PyPI / TestPyPI.
- Publishing uses GitHub's trusted-publisher OIDC flow; no long-lived API tokens exist.
- Each release tag triggers the `publish.yml` workflow automatically.

## Release checklist

1. Bump `VERSION` and move the `[Unreleased]` CHANGELOG entry under the new version, dated.
2. **Sign the release tag:** `git tag -s vX.Y.Z -m "nostos X.Y.Z"` (GPG or SSH signing configured in git). A *signed* tag is what `nostos update --verify` validates; against an unsigned tag `--verify` fails closed by design, so signing is what makes that feature usable for source-clone users. Publish the maintainer public key so users can establish trust.
3. Push the tag: `git push origin vX.Y.Z` - this triggers `publish.yml` (build -> TestPyPI -> PyPI via OIDC, with PEP 740 attestations).
4. Create the GitHub Release from the CHANGELOG section.

## Adding or changing maintainers

New maintainer proposals are handled via a public GitHub issue. The proposal should include:

- The nominee's scope (which subsystems they would own).
- A statement from the nominee that they accept the role.
- Agreement from all existing maintainers.

Transfer of the primary-maintainer role requires an explicit commit that updates this file, signed off by the incoming and outgoing maintainer.
