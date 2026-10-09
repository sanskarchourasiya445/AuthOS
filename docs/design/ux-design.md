# AuthOS — Design

UI/UX design for the hackathon MVP. Goal: make the **control loop visible** (retrieve → evaluate → correct → verify → escalate) and keep the human in charge.

---

## 1. Design Principles

1. **Show the reasoning, not just the answer.** Retry timelines and validator flags are first-class UI.
2. **Every claim is clickable.** Any status or sentence links to its source quote.
3. **Status is never color-only.** Pair color with icon and text.
4. **The human decides.** Approval controls are explicit; the system never auto-finalizes.
5. **Always disclaim.** "Administrative evidence preparation. Not a medical or insurance decision." is visible on every screen.
6. **Minimal and fast.** Few screens, one clear next action each.

---

## 2. Users and Flow

```text
Cases → Run → Evidence Review → Gap Review → Final Review → Packet
```

Primary user: PA specialist. Secondary: clinical reviewer. Demo audience: judges, so the retry timeline and validator rejection must be obvious within seconds.

---

## 3. Screens

### 3.1 Cases (Home)

| Element | Detail |
|---|---|
| Case cards | Patient ID, requested service, policy ID, status (Not run / Running / Needs review / Approved) |
| Primary action | **Run** on each case |
| Demo labels | Case A, B, C tags so presenters can find them quickly |
| Footer | Disclaimer |

### 3.2 Evidence Review (Main Screen)

Two-pane layout.

```text
┌──────────────────────────────────────────────────────────────┐
│ Case B · P-104 · Lumbar MRI · POL-LMRI-001                   │
│ 3 MET   1 AMBIGUOUS   1 MISSING                              │
├──────────────────┬───────────────────────────────────────────┤
│ CRITERIA         │ C2 · Conservative treatment ≥ 6 weeks     │
│                  │ Status: ✔ MET   Verified ✔                │
│ ✔ C1  MET        │                                           │
│ ✔ C2  MET   ◀    │ EVIDENCE                                  │
│ ⚠ C3  AMBIGUOUS  │ ┌───────────────────────────────────────┐ │
│ ✔ C4  MET        │ │ PT_NOTE_004 · 2026-04-22              │ │
│ ✖ C5  MISSING    │ │ "Patient completed PT from March 4    │ │
│                  │ │  through April 22."                   │ │
│                  │ │ ✔ source ✔ quote ✔ patient ✔ dates    │ │
│                  │ │ Duration: 49 days (7 weeks) ≥ 6 weeks │ │
│                  │ └───────────────────────────────────────┘ │
│                  │                                           │
│                  │ RETRIEVAL TIMELINE   (see 3.3)            │
│                  │ VALIDATOR FLAGS      (see 3.4)            │
└──────────────────┴───────────────────────────────────────────┘
```

| Element | Detail |
|---|---|
| Left list | All criteria with status badge; selected row highlighted |
| Right pane | Selected criterion: status, evidence cards, retry timeline, validator flags |
| Summary bar | Counts per status |
| Evidence card | Source ID, date, verbatim quote, validator check marks, computed values |
| "View source" | Opens the full source document with the quote highlighted |

### 3.3 Retry Timeline (Demo Centerpiece)

Vertical stepper per criterion.

```text
● Search 1
  Query: "conservative treatment 6 weeks"
  Found:    treatment type
  Missing:  start date, end date, duration
  Result:   ✖ Insufficient

      ↓  Rewrite targeting missing facts

● Search 2
  Query: "physical therapy treatment start date end date
          duration persistent symptoms"
  Found:    treatment type, start date, end date
  Missing:  none
  Result:   ✔ Sufficient

      ↓

● Verification
  Patient P-104 ✔   Quote exists ✔   Duration 7 weeks ✔
  → MET
```

| Rule | Detail |
|---|---|
| Collapsed by default | When only 1 round was needed (Case A) show a single "Sufficient on first search" line |
| Auto-expanded | When 2+ rounds occurred (Case B, C) |
| Missing facts | Shown as red chips; found facts as green chips |
| Case C | Ends with "✖ Insufficient after 2 retries → Escalated to human" |

### 3.4 Validator Flags Panel

Shows deterministic checks and any rejections.

```text
⚠ Claim rejected
  LLM / source claim:  "about 8 weeks of therapy"   (PT_NOTE_003)
  Computed from dates:  March 4 → April 22 = 7 weeks
  Action:               Claim not used; computed value shown
```

| Check | Display |
|---|---|
| Source exists | ✔ / ✖ |
| Quote verbatim | ✔ / ✖ |
| Patient identity | ✔ / ✖ |
| Duration vs. policy minimum | Computed value and threshold |
| Rejected claims | Amber callout with before/after |

### 3.5 Gap Review

Shown for each non-`MET` criterion.

```text
┌────────────────────────────────────────┐
│ C3 · Persistent symptoms despite       │
│      treatment                         │
│ Status: ⚠ AMBIGUOUS                    │
│ Reason: No explicit supporting         │
│         documentation found.           │
│                                        │
│ Searched: 2 rounds · 6 chunks reviewed │
│                                        │
│ [Add Information] [Accept Gap]         │
│ [Continue Review]                      │
└────────────────────────────────────────┘
```

| Action | Behavior |
|---|---|
| **Add Information** | Opens a text field plus source reference; input is run through validators before it can change status |
| **Accept Gap** | Records the gap in the packet as an accepted gap, with reviewer name and timestamp |
| **Continue Review** | Moves to next gap |

### 3.6 Final Review

```text
┌─────────────────────────────────────┐
│          FINAL REVIEW               │
│                                     │
│ 4 criteria verified                 │
│ 1 ambiguous                         │
│ 1 missing                           │
│ Accepted gaps: 1                    │
│                                     │
│ [Approve Packet] [Edit] [Reject]    │
└─────────────────────────────────────┘
```

| Action | Behavior |
|---|---|
| **Approve Packet** | Requires a confirm dialog; generates the packet |
| **Edit** | Returns to Evidence Review for changes |
| **Reject** | Requires a reason; stores it in the audit log |

### 3.7 Packet View

| Section | Content |
|---|---|
| Header | Case, patient, service, policy, date |
| Criteria table | ID, text, status, evidence citation |
| Evidence | Quotes with source ID and date |
| Gaps | Missing and ambiguous criteria, plus accepted gaps and reviewer notes |
| Reviewer decisions | Who approved, when |
| Footer | Disclaimer |

Every sentence about a criterion carries a citation link. Export as downloadable PDF or Markdown (stretch).

### 3.8 Evaluation Page (Extension)

| Element | Detail |
|---|---|
| Ablation table | Rows A–F; columns recall, precision, MRR, status accuracy, false-`MET` |
| Per-trap breakdown | Bar chart by `trap_type` |
| Baseline row | "Whole chart in context" |
| Footnote | "Measured on synthetic gold set of N criteria" |

---

## 4. Visual Language

### 4.1 Status Styles

| Status | Color intent | Icon | Label |
|---|---|:-:|---|
| `MET` | Green | ✔ | MET |
| `MISSING` | Red | ✖ | MISSING |
| `AMBIGUOUS` | Amber | ⚠ | AMBIGUOUS |
| `CONTRADICTED` | Purple or dark red | ⛔ | CONTRADICTED |
| Verified | Green outline | ✔ | Verified |
| Running | Blue | ◌ | Running |

Always show icon plus text label, never color alone.

### 4.2 Typography and Layout

- System sans-serif for UI; monospace for quotes, IDs, and queries.
- Quotes in a distinct block with a left border so they read as source text, not system prose.
- Generous spacing; cards over dense tables.
- Light and dark themes supported via Tailwind tokens; default light for projector demos.

### 4.3 Components

| Component | Notes |
|---|---|
| `StatusBadge` | Icon + label + color |
| `CriterionList` | Selectable rows with badge |
| `EvidenceCard` | Quote, source, date, validator ticks |
| `RetryTimeline` | Stepper with found/missing chips |
| `ValidatorPanel` | Check list and rejection callouts |
| `GapReviewCard` | Actions for non-`MET` criteria |
| `FinalReviewPanel` | Counts and approval buttons |
| `PacketView` | Cited document |
| `Disclaimer` | Persistent footer or banner |
| `SourceViewer` | Document modal with highlighted quote |

---

## 5. Interaction Details

| Interaction | Behavior |
|---|---|
| Run case | Button → loading state with step labels ("Extracting criteria…", "Searching chart…", "Verifying…"); streaming status if built (P1), otherwise a spinner |
| Select criterion | Right pane updates; URL reflects selection |
| Click citation | Opens `SourceViewer` with quote highlighted |
| Add information | Inline form; shows validator result before saving |
| Approve | Confirm dialog stating "You are approving the evidence packet, not the medical or insurance decision." |
| Errors | Plain-language message plus retry; never a blank screen |

---

## 6. States

| State | UI |
|---|---|
| Empty (no cases) | Prompt to run the seed script |
| Loading | Skeletons for criteria and evidence |
| Error | Inline error with retry; log to audit |
| Missing evidence | Explicit "No supporting documentation found after the initial search and up to 2 corrective retries"; never filler text |
| Cached demo run | Subtle "cached result" tag; "Run live" toggle |

---

## 7. Accessibility

- Status conveyed by icon, text, and color.
- Keyboard navigation for criteria list and review actions.
- Sufficient contrast, including on projectors.
- Buttons and focus states clearly visible.
- Semantic headings and landmarks.

---

## 8. Responsiveness

Desktop first (demo on laptop or projector). Tablet: stack criteria list above detail pane. Mobile: not a hackathon priority.

---

## 9. Safety Copy

| Location | Text |
|---|---|
| Global footer | "AuthOS prepares administrative evidence. It does not diagnose, determine medical necessity, or make insurance decisions." |
| Approve dialog | "You are approving the evidence packet, not the medical or insurance decision." |
| Missing evidence | "No supporting documentation found. AuthOS does not infer or fabricate evidence." |
| Data notice | "Demo data is synthetic." |

Avoid any UI language implying predicted approval, scores of "likelihood," or readiness percentages.

---

## 10. Demo-Driven UI Checklist

| Moment | UI must show |
|---|---|
| Case B retry | Expanded timeline: Search 1 fails with named gap → rewrite → Search 2 succeeds |
| Validator rejection | Amber "Claim rejected" with 8 vs. 7 weeks |
| Case C refusal | "Insufficient after 2 retries" and Gap Review with no invented evidence |
| Human control | Approve / Edit / Reject with confirm dialog |
| Real numbers | Ablation table with measured values |

---

## 11. Build Order for UI (Matches `PLAN.md`)

1. Mock API and `Cases` page.
2. `CriterionList` and `EvidenceCard`.
3. `RetryTimeline` and `ValidatorPanel`.
4. Swap to real API; `GapReviewCard` and `FinalReviewPanel`.
5. `PacketView` and `SourceViewer`.
6. Evaluation page (extension).
