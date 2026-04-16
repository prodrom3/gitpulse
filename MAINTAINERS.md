# Maintainers

## Primary maintainer

- **prodrom3** - [github.com/prodrom3](https://github.com/prodrom3)
  - Scope: all code, releases, security response
  - Response SLO (best effort, no commercial commitment): bug reports within 2 weeks, security reports within 72 hours

## Organization

- **radamic** - owning organization and copyright holder for the MIT license

## Escalation path

1. **Bugs, feature requests:** open a GitHub issue at https://github.com/prodrom3/nostos/issues
2. **Security issues:** follow the private disclosure process in [SECURITY.md](SECURITY.md). Do not file public issues for vulnerabilities.
3. **Merge conflicts or build infrastructure:** mention the primary maintainer on the relevant PR or issue.

## Release authority

- Only the primary maintainer tags releases and publishes to PyPI / TestPyPI.
- Publishing uses GitHub's trusted-publisher OIDC flow; no long-lived API tokens exist.
- Each release tag triggers the `publish.yml` workflow automatically.

## Adding or changing maintainers

New maintainer proposals are handled via a public GitHub issue. The proposal should include:

- The nominee's scope (which subsystems they would own).
- A statement from the nominee that they accept the role.
- Agreement from all existing maintainers.

Transfer of the primary-maintainer role requires an explicit commit that updates this file, signed off by the incoming and outgoing maintainer.
