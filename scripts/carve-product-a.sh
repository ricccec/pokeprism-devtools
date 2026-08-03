#!/bin/sh
# Carve product A — the pret/RGBDS assembly library — out of this repo's history.
#
# Run it inside a FRESH clone and nowhere else: filter-repo rewrites history
# irreversibly and refuses to run on a clone that has been worked in.
#
#   git clone --no-local <this repo> /tmp/carve && cd /tmp/carve && sh carve-product-a.sh
#
# The path list is today's four folders PLUS every historical spelling of a file
# now in A. Naming only the four folders carves 73 commits instead of 88 and
# drops A's whole first month — the birth of the LZ decompressor, the sym reader
# and both CLIs. See docs/refactor-phase-0-STATE.md, "The ledger".
#
# Rebuild the ledger before reusing this; phases 1 and 2 move files, and every
# move adds a row. Read the rows off the renames git recorded, walking the chains
# backward from today's paths:
#
#   git log --diff-filter=R --name-status -M --format='' \
#     | awk '$1 ~ /^R/ {print $2" -> "$3}' | sort -u
#
# Not `git log --follow`, which invents ancestry for empty files.

set -e

git filter-repo \
  --path src/pokeprism_devtools/shared \
  --path src/pokeprism_devtools/wiring \
  --path src/pokeprism_devtools/usage \
  --path src/pokeprism_devtools/sym_lookup \
  \
  `# the flat layout, f5e752b .. c8a3e9a` \
  --path src/pokeprism_devtools/blockdata.py \
  --path src/pokeprism_devtools/constants.py \
  --path src/pokeprism_devtools/lz.py \
  --path src/pokeprism_devtools/mapfile.py \
  --path src/pokeprism_devtools/paths.py \
  --path src/pokeprism_devtools/people.py \
  --path src/pokeprism_devtools/sym_lookup.py \
  --path src/pokeprism_devtools/symfile.py \
  --path src/pokeprism_devtools/usage.py \
  --path src/pokeprism_devtools/viewer.py \
  \
  `# the _lib/ layout, before f5e752b` \
  --path _lib/blockdata.py \
  --path _lib/constants.py \
  --path _lib/lz.py \
  --path _lib/paths.py \
  --path _lib/people.py \
  --path _lib/symfile.py \
  \
  `# the three that went to hacks/prism in b0298cc and came back in 3a1fae6` \
  --path src/pokeprism_devtools/hacks/prism/blockdata.py \
  --path src/pokeprism_devtools/hacks/prism/people.py \
  --path src/pokeprism_devtools/hacks/prism/spritevram.py \
  \
  `# before the src/ layout existed` \
  --path sym-lookup/sym-lookup.py

# Every branch was rewritten, not just the tip: check ancestry, then prune.
#   git branch --format='%(refname:short)' | while read b; do
#     git merge-base --is-ancestor "$b" <tip> && git branch -D "$b"
#   done
