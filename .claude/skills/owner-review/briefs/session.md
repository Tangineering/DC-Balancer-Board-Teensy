<!-- Review-session brief template (owner-review skill, section 4). Fill every field in angle
     brackets and change nothing else. Copy <background block> verbatim from PROJECT.md. Delete
     this comment and each unused optional line before the brief is sent. -->

Title: Review <n>/<N>: <item IDs> (<topic>)

### prompt

Use the `owner-review` skill: you are review session <n> of <N>. Walk <owner> through the owner review of the items below, one at a time, and collect a ruling on each. <one sentence: what downstream work these items unblock>.

<items block: one bullet for each item, in review order, in this form>
- `<item ID>` <item name> (<record lines, for example "LAYOUT_DECISIONS.md section 11 item 14, D-41">): <the current state in one or two lines, with the design files and values>. Put these questions to <owner> explicitly: (1) <explicit question>; (2) <explicit question>. <optional: Follow-ups, each to raise or drop: <follow-up>; <follow-up>.> <optional: Opt-in, yes or no: <costly run, download or order>.> <optional: Images to send as files: <paths>.> <optional: Also mention: <fact the owner should know>.>

For each item:
1. Read the item's record lines and the design files that carry it (footprint, board, generator, BOM row). Check the current value yourself before you present it.
2. Present to <owner>, briefly: what the item is, which parts need an approval and which need a value from <owner> or a primary source, the proposed resolution, and the questions above. Point to exact files and lines. Send images and rendered output as files.
3. Ask for the ruling: approve, approve with changes, or reject. On "approve with changes", ask for the exact replacement text, value or rule. Answer questions read-only from the repository and from primary sources read in place.

Report to the orchestration session `<orchestration session id>` with SendMessage, in the reply form of the `owner-review` skill, section 6: one block for each settled item with the ruling, <owner>'s words quoted verbatim, each proposed row's fate (accept, amend or reject, for each lettered part where <owner> split them), the answers to the explicit questions with any value and its source, each follow-up raised or dropped, each opt-in yes or no, and each change as <owner>'s exact text. End with "Remaining:" and the unsettled items, or "none". Send the reply when all items are settled, or as soon as <owner> stops or pauses before then. Then end your turn.

### background

<background block>

<per-round facts: one line for each fact that is true for this round only, or delete this line>
