## General rules

- Do what has been asked; nothing more, nothing less
- NEVER create documentation files unless explicitly requested
- NEVER save working files or tests to root — use `/src`, `/tests`, `/docs`, `/config`, `/scripts`
- ALWAYS read a file before editing it
- ALWAYS run tests after code changes
- NEVER commit secrets, credentials, or .env files
- NEVER add a `Co-Authored-By` trailer to user commits unless this project's `.claude/settings.json` has `attribution.commit` set (#2078). The Claude Code Bash tool may suggest one in its default commit-message template — ignore it. `Co-Authored-By` is semantic authorship attribution under git/GitHub convention; the tool is the facilitator, not a co-author.

## Functions
- **Name functions with a verb and its object** — say what the function does
  *to what*. A function *does* something, but a bare verb
  (`discover`, `process`, `handle`, `run`) is barely better and still tells the
  reader nothing. The test that
  matters: reading the name alone, could someone answer *what does this return or
  change?* `get_registered_hacks` passes; `discover` does not. When a verb needs
  no object because the object is the whole module (`mount`, `build`), that is
  fine — the object is implied, not missing.
- Keep each function at **one abstraction level**. Smells: more than 2–3 levels
  of nested blocks, or a body longer than ~30 LOC. The test: every line in a
  function should answer the same kind of question. No function should be > ~50 LOC.
- Validate input at system boundaries (user input, external APIs, file formats) —
  and **trust internal code and framework guarantees**. No defensive validation
  inside private functions or between layers we control.
- Keep every magic value named. A number or string that encodes a protocol
  decision — a record length, a bank, an opcode, a sentinel — is a fact, and a
  fact needs a name to be checkable.


## File size

Size is a proxy for responsibility count, and that is the thing actually being
measured. **One file holds one or two responsibilities**, which in practice
lands around **~150 LOC**.

- **Over 250 LOC** is a smell, not a violation: it usually means responsibilities
  have been stuffed in together. Read it as a prompt to look.
- When a cluster of related responsibilities piles up, **give each file one or
  two and put the files in a folder** whose name says what domain they share.
  The folder name is the explanation; if it can't be named, the grouping is
  wrong.
- **Tests are exempt.** Let them be as big as they need.

## Naming files and folders

A **folder is an address** — its job is to answer *"what kind of things are
here?"*. Use GBC rom-hacking terms like `save` or `VRAM`, or pret domain names
like `overworld` or `pokemon-stats`. Architecture-adjacent names (`shared/`,
`core/`, `services/`) are also fine.

A **file that defines a domain entity must carry that entity's name** — its job
is to answer *"what is this?"*. Never use an architectural noun where a domain one is
available.

## Comments

A code file should explain itself. Nobody reads 100 lines of prose and then 100
lines of code saying the same thing — if the code needs the prose, it needs better
function names, a responsibility dropped, and functions at a single abstraction
level. Refactoring beats comments. The header comment states intent plus anything
genuinely non-obvious or contestable. Delete the rest.

**One exception, and it is narrow:** prose recording a **measurement or a
falsification** ("reading polished with vanilla's record returns exactly one
palette, so the box silently stops suggesting") is a fact that cost work to find.
Route it to a test, a commit body, or a doc. Never simply delete it.

## Commit style

- **Imperative mood.** "Add", not "Added" or "Adds" — the subject completes the
  sentence "this commit will…".
- **Subject under 50 characters**, first line.
- **The body explains *why*.** What was wrong with the previous state, and how
  this change fixes it. What changed is already in the diff; what the diff can
  never show is what was broken and what it cost.
- **The scope is a module, package, feature, or component** — a name that will
  still mean something in a year. **Never a phase number or a plan name.**
  Plans are throwaway specs; git history is not, and `feat(9a,9b)` is unreadable
  the moment the plan it referenced is gone.