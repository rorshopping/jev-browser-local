# Security policy

## Reporting a vulnerability

Email **joey@jkudish.com** with "jev-browser security" in the subject. Include:

- the package version and how you installed it;
- a minimal reproduction (task, start URL, environment);
- the impact you observed or expect.

Please do not open public issues for vulnerabilities. There is no bug bounty and no committed response time; reports are handled as maintainer time allows.

## Scope

jev-browser runs a headless browser and makes network calls to the TypeSafe API and, when configured, one typing provider. It navigates to URLs you supply and can follow links from those pages. Treat the service environment it runs in as reachable by the pages it visits: run it in a container or restricted network if your environment has private endpoints you do not want touched.

Only the latest released version receives fixes. There is no support policy for older versions yet.
