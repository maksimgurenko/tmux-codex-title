# Contributing

Fork the repository, run the README's tests, and submit a focused patch with
its regression scenario. Runtime dependencies are Linux tmux, Python 3.10+, and
procps; tests require no Python packages. Keep code independent of maintainer
credentials and desktop integrations. A fork can use the same files and commands;
change only its repository URL in installation examples while retaining license
attribution.

Before a release, run the complete test suite and Bash syntax check. Test the
entry point from a fresh checkout, including a checkout path containing spaces.
Review outgoing files, commit identity, and Git history, and scan for secrets.
Keep machine-specific installation records outside this repository. State the
versions actually tested and any remaining limitations.

Tag the tested commit as `vMAJOR.MINOR.PATCH`, push only the intended branch and
tag, and create a GitHub release with behavior changes and validation results.
The checkout itself is the release artifact; no compiled binary is required.
Update the README's installation tag alongside the corresponding release.
