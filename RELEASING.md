# Releasing

A release here exists so people can cite the repository. Zenodo archives each GitHub release and
gives it a DOI, reading the author, title and version from `CITATION.cff`. `bin/release` does the
repository side. The Zenodo side is two manual steps, both only needed around the first release.

## Before the first release: keep the road to a paper open

If this work becomes a paper, the switch is cheap. `CITATION.cff` keeps its software entry and
gains a `preferred-citation:` block with `type: article`, and GitHub's cite button then shows the
paper. The software DOI stays valid and the paper cites it. Citations made to the software DOI
before then do not move to the paper, so add the block the day a preprint exists.

Do these before the first DOI exists.

- [ ] Register an ORCID at orcid.org and add it to the author in `CITATION.cff` as
      `orcid: "https://orcid.org/0000-0000-0000-0000"`. It ties the same person together across
      Zenodo, arXiv and a venue.
- [ ] Decide to tag a release at each results milestone, not only when a release feels due. A
      paper can then cite the exact version behind each table.
- [ ] Keep one name form everywhere. "Jason Carver" is already in the cff, `LICENSE` and the git
      history.
- [ ] Stay the sole copyright holder of the prose. The repository is GPL and a paper's text and
      figures will likely be CC-BY. You can relicense your own notes. Outside contributions to
      them would need permission from each author.

Decide these before the first DOI exists.

- [ ] Double-blind venues. A public repository with your name and a DOI deanonymizes a
      submission. arXiv and most ML venues do not mind, and anonymized mirrors exist for the ones
      that do. Pick the kind of venue before the DOI spreads.
- [ ] Run data. `outputs/` is git-ignored, so no release archive holds it. A paper would need a
      separate Zenodo dataset deposit. Scrub it first, because `outputs/**/infer.log` holds a
      live OAuth token.

## Once, before the first release

Zenodo archives only releases created after the repository is switched on. A release cut before
that gets no DOI, and Zenodo does not pick it up later.

1. Log in at zenodo.org with the GitHub account that owns the repository. Zenodo installs a
   webhook, so the account needs admin rights on it.
2. Open https://zenodo.org/account/settings/github, press "Sync now" if the repository is missing, and
   flip its switch on.

`bin/release` cannot check this switch. The sandbox token gets a 404 from GitHub's webhook API.
So the first release takes `--zenodo-enabled`, which is you saying the switch is on.

## Every release

Run from the repository root, on main.

    bin/release v0.1.0 --dry-run --zenodo-enabled   # checks, then prints the plan
    bin/release v0.1.0 --zenodo-enabled             # the first release
    bin/release v0.2.0                              # later ones, once the cff has a doi

The tool writes the version and today's date into `CITATION.cff`, validates the file, commits it
alone, tags the commit, pushes main with the tag and creates the GitHub release with generated
notes. Pick the version by hand. Nothing here depends on semver meaning, so bump the minor number
when the findings change and the patch number for fixes.

Two things to know before running it.

- Pushing main publishes every local commit on main, including another agent's. Look at
  `git log origin/main..main` first if that matters.
- Uncommitted work in the tree stays out of the release commit, staged or not.

The tool refuses, before changing anything, when the version is not `vX.Y.Z`, the tag already
exists here or on origin, the branch is not main, `CITATION.cff` has uncommitted edits, or
origin/main has commits this clone lacks.

## Once, after the first release

Zenodo takes a few minutes. The repository's row at https://zenodo.org/account/settings/github
then shows the release with a DOI badge. If it shows an error instead, one known cause is a
`CITATION.cff` Zenodo could not parse, which the tool's validation step should have caught.

The record page lists two DOIs. One names this version. The other, under "Cite all versions",
always resolves to the latest. Put the second one in `CITATION.cff` as a top-level line:

    doi: 10.5281/zenodo.NNNNNNN

Then update the "How to cite" section of the README, which still says there is no DOI, and add
the badge Zenodo offers on the record page. Commit both on main. The DOI reaches the cff one
release late by design, since Zenodo mints it only after the release exists.

From then on the `doi` line tells `bin/release` that Zenodo works, and the flag is not needed.

## When a step fails

Everything up to validation leaves the tree as it was. After that the tool runs four commands in
order: commit, tag, push, create the release. If one fails it stops and prints the commands still
to run. Fix the cause and run those by hand. Do not rerun `bin/release` with the same version. It
will refuse, because the tag now exists.

To abandon a release that failed before the push, delete the tag with `git tag -d vX.Y.Z` and
revert the release commit. After the push, cut the next patch version instead. Zenodo records are
permanent, and a tag other people may have fetched should stay where it is.
