# Design Decisions

This document explains why APEX's UI looks the way it does — what was chosen, what was rejected, and why.

## Design philosophy

APEX is a **productivity tool**, not a marketing site. The reference set is Linear, Vercel, Raycast — not Awwwards Site of the Year winners. Tools that get used daily need to disappear; tools that get used once need to entertain. APEX is the former.

### Three rules I followed

1. **The user's resume should always be the most important thing on screen.** Everything else (UI chrome, branding, animations) is secondary.
2. **Show progress, not spinners.** A spinner says "we're doing something." A live log says "here's exactly what we're doing." Live logs make slow operations feel fast.
3. **Honesty over polish.** When data is sparse, say "low confidence." When a source fails, show ✗ not ✓. Users trust tools that admit limits.

## Visual system

**Color palette**

| Token | Value | Usage |
|---|---|---|
| `--void` | `#000` | Page background |
| `--deep` | `#0a0a14` | Surface (cards, panels) |
| `--surface` | `#0f0f1a` | Raised surface (inputs) |
| `--blue` | `#4f8ef7` | Primary action color |
| `--blue-soft` | `#6fa3f8` | Highlighted text |
| `--cyan` | `#00e5cc` | Gradient accent |
| `--green` | `#22c55e` | Success state |
| `--amber` | `#f59e0b` | Warning state |
| `--red` | `#f05252` | Error / weak state |
| `--t1` | `#ededf2` | Primary text |
| `--t2` | `#a8a8b8` | Secondary text |
| `--t3` | `#6b6b80` | Tertiary text (labels, captions) |

The dark canvas was chosen for **screen comfort during long resume work sessions**. Light mode would be added before launch — dark mode is a power-user default.

**Typography**

- Plus Jakarta Sans (UI) — friendly, modern, readable at small sizes
- Fira Code (mono) — for resume content and numerical scores

Both are free Google Fonts. No subscription typography because dependencies should be minimal.

**Spacing and rhythm**

- Base unit: 4px (all paddings/margins are multiples)
- Card padding: 14-18px
- Section gaps: 18-24px
- Border radius: 4px (small elements), 6-8px (cards)

## Information architecture

### Tab navigation
16 tabs would normally be a usability disaster. Two design choices fix this:

1. **Hide tabs until they have data.** The 4 Phase 8 tabs (Jobs, LinkedIn, Outreach, Velocity) are `display: none` until their data event arrives. No empty tabs, no broken-feeling UI.
2. **Horizontal scroll, not wrap.** When tabs exceed viewport width, the nav bar scrolls horizontally with a thin scrollbar — rather than wrapping to two rows. This keeps the visual hierarchy clean and the tab strip a fixed height.

### Sidebar
320px fixed-width left sidebar holds:
1. **Configure section** — target role, industry, seniority, JD textarea, JSearch key
2. **Resume input** — drag-drop zone + textarea (mutually populated)
3. **Agent log** — live SSE feed
4. **Cost box** — runs cost (appears after first run)
5. **Version history** — last 10 runs (appears after first run)
6. **Action buttons** — PDF/DOCX/TXT export, Copy Letter, Job Tailor

The sidebar is intentionally dense. Power users who run APEX repeatedly want access to everything in one place — not buried behind menus.

## Interaction patterns

### Streaming feedback
Every agent step appears in the log as it happens. The log component uses:
- `addLog(msg, kind)` where kind is `info` / `ok` / `warn` / `error`
- Event count badge in header (e.g., "67 EVENTS")
- Auto-scroll to latest entry

This makes a 30-second agent run feel like 30 seconds of progress, not 30 seconds of waiting.

### Status indicators
Each tab has a "reveal" state and a "data" state:
- **Hidden (default)** — tab not shown
- **Revealed** — tab visible, empty state explains how to populate it
- **Populated** — tab has real data

This is communicated through:
- Tab visibility (CSS `display: none` → `display: flex`)
- Empty state messages with clear CTAs ("Click X to populate this tab")
- Status badges (e.g., "✓ Active" for JSearch when key is configured)

### Error handling
Errors appear as a **persistent banner above the main content**, not as toast notifications. Toasts disappear before users can read them; banners stay until dismissed or a successful action clears them.

The error banner color is muted (red on dark red) — visible but not panic-inducing. Users encountering errors are already stressed; the UI should communicate "this is fixable" not "everything is broken."

## What was rejected

### Light mode
Skipped for v1. Power-user dark mode covers 80% of the use case. Light mode requires retesting every component for contrast and is best added in a focused pass.

### Onboarding tour
A guided "click here to start" walkthrough was considered. Rejected because:
1. The sidebar is already a step-by-step guide (top to bottom)
2. Onboarding tours feel patronizing to power users
3. The empty states explain themselves

### Animations everywhere
Tabs don't slide, cards don't fade in, scores don't tween. Every animation is a tax on perceived speed. Animations were limited to:
- Tab active state (subtle underline transition)
- Hover effects on buttons (border color change)
- Loading dots in the log

The actual ATS score animation (0 → 85 ring) was prototyped and cut. It looked good but added 800ms to the perceived run time — unacceptable for a tool people use repeatedly.

### Modal dialogs
No modals anywhere. Every interaction happens inline or in the sidebar. Modals feel like interruptions; inline editing feels like flow.

## Mobile

The current implementation is desktop-first. Mobile breakpoints exist but aren't optimized — the sidebar stacks above the main content and the 16-tab nav becomes a horizontal-scroll strip.

For a hosted version, mobile UX would need:
- Collapsible sidebar (drawer pattern)
- Bottom-sheet for tab navigation
- Touch-friendly hit targets (min 44px)
- Reduced font sizes (currently 14px base; mobile wants 13-14px)

## Accessibility (current state, honest)

Partial:
- ✅ Semantic HTML (proper `<button>`, `<nav>`, `<main>`, `<aside>`)
- ✅ Keyboard navigation works (tab order is logical)
- ✅ Color contrast passes WCAG AA for primary text on dark surfaces
- ⚠ Some secondary text (`--t3` on `--deep`) is borderline AA
- ❌ No screen reader testing has been done
- ❌ No keyboard shortcuts beyond browser defaults
- ❌ No ARIA labels on icon-only buttons

For a hosted version, accessibility would need a dedicated pass. For a local power-user tool, this baseline is acceptable.

## Things I'd polish given more time

In rough priority order:

1. Better error messages that map technical errors to user-friendly explanations
2. Micro-animations on the score ring, ATS chip, and progress bar
3. A proper print stylesheet for browser-native PDF export (alternate to jsPDF)
4. Skeleton loaders for tabs while data is generating
5. Light mode
6. Mobile-optimized layout
7. Keyboard shortcuts (Cmd+K command palette, Cmd+E export, etc.)
8. Inline editing of the optimized resume with live ATS-score recalculation
9. A11y pass with screen reader testing
