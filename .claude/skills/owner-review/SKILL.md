---
name: owner-review
description: Owner-review protocol for this repo - inventory everything that waits on the operator (open TODO(verify) items, proposed design changes, orchestrator defaults, order gates, agent-proposed follow-ups and opt-ins), group the entries into read-only review sessions of 3 to 5 items with numbered titles, brief each session from briefs/session.md, walk the operator through one item at a time, relay the operator's rulings verbatim to the orchestration session, then record and apply them. Use in the orchestration session when operator items accumulate (after a design round, an overnight run or a HIL campaign), when the operator asks to review or asks for review sessions on a set of items (for example the blockers of a PCB order), and in any session whose brief opens with "Review n/N".
---

# Owner review

The operator approves engineering content and rulings before an item is closed. Agents land the
agent-verifiable half of an item, and the item waits for the operator. This skill turns the
accumulated items into short, ordered review sessions. Each session walks the operator through
its items and relays the rulings to the orchestration session, which records them.

Everything specific to this repository is in `PROJECT.md` beside this file: the operator's name,
the registers per work area, the attribution form, the unattended-run summary files, the fixed
background block, and the changes the orchestration session must not apply itself. Read
`PROJECT.md` before step 1 of any procedure below.

## 1. When to use

The orchestration session uses this skill in these conditions:

- Open operator items, proposed design changes, orchestrator defaults or agent-proposed
  follow-ups have accumulated.
- An unattended run has ended, and the operator is back.
- The operator asks to review, or asks for review sessions on a named set of items.

A review session uses sections 5 to 7 only. It recognizes itself by the brief title
"Review n/N: ...".

## 2. Inventory

The inventory is the list of everything that waits on the operator, in the work area that
`PROJECT.md` section 2 names. When the operator names a set of items (for example "the blocking
items of the PCB order"), the inventory is that set; add only the follow-ups and opt-ins that
belong to those items.

1. Open the unattended-run summary file of the work area, if one exists for this run.
2. List every open item of the work area's open-items register that is in scope.
3. List every proposed design change and every orchestrator default the operator may override.
4. List every follow-up that an agent proposed and nobody raised or dropped.
5. List every opt-in that waits on a yes, for example a costly run, a download or an order.
6. Attach each follow-up, default and opt-in to the item that it concerns.
7. Keep an entry that concerns no item as its own inventory entry.
8. For each item, collect the evidence the operator needs: the record lines, the current value
   in the design files, and what the item is checked against (a drawing, a datasheet table, a
   fab capability). Verify each claim before it goes into a brief.

## 3. Grouping and order

1. Group the entries by topic and by the files and sources that they share.
2. Put 3 to 5 entries in each group.
3. Put an entry with much content to approve in a smaller group.
4. Order the groups by the downstream work that each group unblocks, most first.
5. Number the groups in that order.
6. Give each session the title "Review n/N: <items> (<topic>)".

The operator takes the sessions in title order. All sessions can start at once, because the
order is in the titles.

## 4. Brief

Each session gets one brief, filled from `briefs/session.md`. Fill every field in angle
brackets and change nothing else. The background block comes from `PROJECT.md` verbatim.

The brief must contain these data:

- The title, with its number "n/N".
- Each item, with its record lines, the current value in the design files, and what the
  operator must approve or supply.
- Explicit questions for each item. These are required. A session performs best when it knows
  the exact open choices.
- The follow-ups of each item, written as "raise or drop" questions under that item.
- The opt-ins of each item, written as "yes or no" questions under that item.
- The id of the orchestration session, so that the session reports with a direct message.
- The per-round facts, for example another session's uncommitted files in the checkout.

Do not tell a session to search for the orchestration session. Give it the id.

If the harness cannot start side sessions, use the fallback in section 9.

## 5. Session conduct

A review session is a read-only conversation with the operator. Take the items one at a time,
in brief order.

1. Read the item, its record lines, and the design files that carry it.
2. Tell the operator what the item is, with exact file and line pointers.
3. Tell the operator which parts need an approval and which need a value the operator supplies
   (a drawing dimension, a part number, a fab answer).
4. Give the proposed resolution, with its lettered parts.
5. Put each explicit question from the brief to the operator.
6. Put each follow-up to the operator as "raise or drop".
7. Put each opt-in to the operator as "yes or no".
8. Ask for the ruling: approve, approve with changes, or reject.
9. When the operator approves with changes, ask for the exact replacement text, value or rule.
10. Record the operator's words verbatim.
11. Go to the next item.

Send images, plots and rendered output to the operator as files in the conversation. Use the
harness tool that sends a file to the user. If the harness has no such tool, give the absolute
path of each file.

Answer the operator's questions from the repository and, where `PROJECT.md` allows it, from
manufacturer pages read in place. Do not guess; say what is not in the repository or not
confirmed by a primary source.

When the operator states a ruling, do not rewrite it. Quote it. A change that the operator
states as exact text needs no second review round. A change that the session re-words does.

## 6. Reply contract

Send the reply to the orchestration session by direct message, to the id in the brief. Send it
when all items are settled. Send it also when the operator stops, pauses, or leaves the review
before all items are settled. A settled item is never held back for an unsettled one.

The reply has one block for each settled item. Each block contains these fields:

- **Item:** the item ID and name.
- **Ruling:** approve, approve with changes, or reject.
- **Operator's words:** the operator's statement, quoted verbatim, with the chat date.
- **Record rows:** the fate of each proposed row or default (accept, amend, or reject), for
  each lettered part where the operator split them.
- **Answers:** the answer to each explicit question in the brief, with any value the operator
  supplied and its source (drawing, datasheet, page).
- **Follow-ups:** each follow-up raised or dropped, with the operator's words.
- **Opt-ins:** each yes or no, with the operator's words.
- **Changes:** each change, as the operator's exact text, value or rule, with its target file.

After the blocks, add a line "Remaining:" that names each unsettled item, or "none". Then end
the turn.

## 7. Read-only rules

A review session reads and talks. It does not change the repository or start work.

- Do not edit, create or delete files.
- Do not commit, and do not change branches.
- Do not write to the registers named in `PROJECT.md`.
- Do not start costly runs, workflows, routing runs, HIL suites or application sessions.
- Do not download files and do not order anything.
- When the operator says yes to an opt-in, relay the yes. The orchestration session acts on it.
- Run only read-only commands, with the interpreters that `PROJECT.md` names.

## 8. Orchestrator intake

The orchestration session records each reply. It does this work for each block.

1. Write each ruling into the work area's decision register with the attribution form from
   `PROJECT.md`.
2. Close or amend each open item in the open-items register with the operator's words and the
   date, using the register's "Closed" / "Amended" / "Superseded" convention.
3. Apply each verbatim change under the item's ID, in a commit that names the item.
4. Give each change that needs new derivation or regeneration (a footprint, a board rebuild, a
   routing run, a fab package) to an execution agent or run it through the work area's
   generator, then verify it as the work area requires (for the PCB: DRC, constraint check,
   export).
5. Return an item to the operator when the derived change lands, unless the operator stated
   the change as exact text.
6. Raise each accepted follow-up in the work area's queue or open-items register.
7. Record each dropped follow-up beside the closed item.
8. Act on each opt-in yes as a normal round step.
9. Return each rejected item to the open-items register, with an "Amended" line.

`PROJECT.md` names the kinds of change that the orchestration session must not apply itself.
Give a verbatim change of that kind to an execution agent or to the operator, as `PROJECT.md`
says.

When a reply names remaining items, keep them in the inventory for the next review.

## 9. Fallback without side sessions

Some harnesses cannot start a separate session. In that case, do the review in the
orchestration session.

1. Take the groups in title order.
2. Walk the operator through each group as section 5 tells a review session.
3. Write the reply blocks of section 6 into the session's notes.
4. Do the intake of section 8 for each group before the next group starts.

The read-only rules of section 7 apply during the walk-through. The orchestration session
writes only during the intake.
