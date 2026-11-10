# Security policy

mindyard serves personal knowledge bases, so security reports are taken seriously.

## Reporting

Please report vulnerabilities privately through GitHub: on the repository page,
open the **Security** tab and choose **Report a vulnerability**. Do not open a
public issue or pull request for a vulnerability.

Include what you found, how to reproduce it, and the version or commit
affected. You should get a first answer within a week.

## Scope

Of particular interest: anything that lets a caller read or write outside its
own wikis (path confinement, tenant isolation), bypass authentication or the
access policy, lose a concurrent edit despite the version check, or alter
`wiki.yaml` or `raw/` through the MCP tools.

## Supported versions

mindyard is pre-release: only the latest commit on `main` receives fixes.
