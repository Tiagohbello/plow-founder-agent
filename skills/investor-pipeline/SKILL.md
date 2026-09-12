---
name: investor-pipeline
description: "Read and update the founder's investor pipeline CSV through Latch, and answer investor status questions from evidence."
version: 1.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, investors, pipeline, csv, latch]
    related_skills: [founder-context, gmail, founder-calendar, founder-scheduling]
---

# Investor Pipeline

Use for the founder's investor relationships.
`founder-scheduling` owns the hold/send/confirm workflow and reads this
file's `Holds`/`Proposed` columns; this skill owns the file and helper.

## File

`~/Plow/investors/pipeline.csv` — inside the Plow folder Latch auto-approves,
so no Mac dialog interrupts an update. For a file this skill creates from
scratch, columns are in order: `Investor, Contact info, Firm, Status,
Holds, Proposed`. An imported file keeps its own column order, with any
missing canonical column appended at the end. One row per relationship,
`Investor` is the key. Split a firm's row in two when a thread shows a
distinct person there, rather than folding them into one.

`Investor` and `Firm` are stable keys: the calendar lookup below finds a
hold by title, composed from both, so release outstanding holds before
renaming either. A rename is a spreadsheet edit the founder makes
directly — this helper offers no rename or delete.

- `Holds` — held options as human text, `; `-separated, timezone-qualified:
  `Tue 9/15 11:30–12:00 PT`. No event ids; a hold's calendar event is found
  by title `HOLD — <Investor> / <Firm>` (just `HOLD — <Investor>` when
  `Firm` is blank) and start time. `Holds` is exactly the set of times
  `Proposed` refers to — changing `Holds` on a row whose `Proposed` is
  non-blank means those times must be re-sent and `Proposed` rewritten in
  the same `set` call.
- `Proposed` — blank until held times are sent; then `<channel> <date>
  (<thread ref>)`, channel one of email, text, plow.
- `Status` — compact factual state and next action, in precise words:
  drafted / sent / held / confirmed / completed. A hold is not an
  invitation; a proposal is not a meeting.

## Change a row

Read the file fresh with `plow_read_file` every time — never from a copy
read earlier in the conversation. Save it to a temp file, then run the
helper through the agent's code-execution tool using the argument-list
form — never by assembling a shell command string:

```python
import os, subprocess

helper = os.path.join(os.environ["HERMES_HOME"],
                      "skills/investor-pipeline/scripts/pipeline.py")

subprocess.run([
    "python3", helper, "set", tmp,
    "--investor", name,          # each value is its own list element
    "--status", status,
    "--holds", "",                # an empty string element clears the cell
], check=True)
```

Every value is its own list element — the way `tests/test_pipeline.py`
invokes the helper, only the flags actually changing are passed (here
`--contact`, `--firm`, and `--proposed` are omitted, so those cells stay
untouched). There is no shell to assemble a command string into, so there
is nothing for `'`, `"`, `;`, `$(...)`, or a newline to escape into, all of
which are valid text in an investor name or status. `set` mutates `tmp` in
place from the copy you just read, and the upload replaces the destination
whole — there is no conditional write, so a save landing mid-upload is
lost and no re-read prevents it: update this file only when the sheet
isn't being edited, asking the founder to close it if it's open.
Immediately before `plow_write_file`, `plow_read_file` the destination and
diff it byte-for-byte against the copy `tmp` was built from; different
means they edited it while you worked — abort without writing and redo the
read → `set` sequence against that content. That catches an edit already
saved, not one saved mid-upload. Confirm a successful write the same way:

```python
subprocess.run(["python3", helper, "show", tmp, "--investor", name], check=True)
```

Only the named flags change; every other row and column is preserved. Pass
an empty string as a flag's value (`"--holds", ""`) to clear a cell; omit
the flag entirely to leave the cell untouched. `set` refuses (exit 1,
nothing written) on a name that already matches more than one row — surface
that to the founder, who renames one of the rows in the sheet to break the
tie (never guess or merge them yourself).

## Keep it current

An update is part of the action, not a follow-up: whenever this skill is
asked to record a change to a row — a status update, a hold, a proposal —
make the `set` call before the turn is done. Use the exact status words
above, never a looser paraphrase; other skills that read this file (like
`founder-scheduling`) depend on them.

## Status questions

Before answering where things stand, check email, texts (Messages through
Latch), and the agent's own Plow conversations (`session_search`), not just
the row. A search hit is a lead, not proof: validate its From, To, and date.
Assistants and chiefs of staff emailing or texting on an investor's behalf
still schedule for the named investor. A newsletter, auto-reply, or received
portfolio update is not a meeting request; do not update `Status` from one.

## First use

If the file is missing and the founder names an existing pipeline CSV of
theirs, read it with `plow_read_file`. Map the founder's headers onto the
canonical ones yourself — show the founder the mapping (their column →
canonical column, e.g. `Name` → `Investor`) and use their answer, keeping
any column with no canonical match as-is. Write the mapped file, in
canonical column order, with `plow_write_file` to
`~/Plow/investors/pipeline.csv` — the helper is not an importer. Confirm by
`plow_read_file`-ing that same destination into a fresh temp file and
running `pipeline.py show <fresh-tmp>` on it — re-showing the file you built
locally would only prove your own copy is right, not what actually landed
on the Mac. Tell the founder the new path, and leave the old file untouched.
