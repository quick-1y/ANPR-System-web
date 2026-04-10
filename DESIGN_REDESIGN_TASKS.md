# ANPR Web — Design Redesign Task List

Status: partial implementation — quick-win batch done (C1, C2, B1, B2, B3, F3, DK2, T3, N2-desktop, M2, M3, P4, G5).
Scope: visual design, UX, hierarchy, spacing, typography, colors, states, responsive behavior. Product logic is out of scope unless a UX issue clearly requires it.
Source reviewed: `app/web/index.html`, `app/web/styles.css`, screen inventory from `app/web/js/*`.

---

## 1. Honest assessment of the current UI

The product works, but the interface reads as a "sci-fi operator dashboard template" — heavy monospace type, gold-on-near-black, neon glows, uppercase letter-spaced labels everywhere, and HUD-style pills in the topbar. That visual language is fine for a demo, but it fights against the product's actual job: letting operators scan events, configure channels, and manage lists quickly and calmly.

Concrete problems found in the code:

1. **One font doing all jobs.** `--mono` and `--sans` both map to `Eexpresswayfree` (`styles.css:9–30`). Google Fonts loads DM Sans + Space Mono in `index.html:7–10` but they are never used. Result: labels, numbers, body text, and headers all share one stylized display face — this is the single strongest reason the UI feels "AI-generated", not human-designed.
2. **No consistent type scale.** Hardcoded `9px / 10px / 11px / 12px / 13px / 14px / 16px` scattered across the stylesheet with no tokens. Half the UI reads at ≤10px, which is unreadable on laptops and broken on mobile.
3. **Over-reliance on UPPERCASE + letter-spacing.** `.panel-header`, `.s-card-header`, `.snav-label`, `.obs-label`, `.filter-label`, `.cam-label`, `.modal-label`, `.topbar-title`, event meta, journal headers — almost every label is uppercased and tracked. The product loses hierarchy because *everything* looks like a section header.
4. **Gold accent overused.** `#e8a838` is on the primary button, active tab, focus ring, hover border, active snav, active ch-item, plate label, event hot-state, list item active… there is no secondary accent, no informational blue, no neutral selection. Everything competes for attention.
5. **Gradient/glow button + transform on hover** (`.btn-primary`, `.auth-btn`) looks "gamified". Primary actions should be flatter and calmer in a production tool.
6. **Radius inconsistency.** Tokens `--radius-sm/--radius/--radius-lg` exist but the stylesheet uses `3, 5, 6, 7, 8, 10, 11, 14, 99px` ad-hoc (e.g. `.ttab` `11px`, `.ch-list` `8px`, `.badge` `5px`, `.icon-btn-sm` `6px`). No visual rhythm.
7. **Border / divider system is ad-hoc.** Mixes `var(--border)`, `var(--border2)`, `rgba(255,255,255,0.025)`, `rgba(255,255,255,0.018)`, `rgba(255,255,255,0.012)` in neighboring rules. Inside dark mode this is invisible noise; in light mode most of it disappears.
8. **Light theme is broken.** `body[data-theme="light"]` only flips a handful of tokens (`styles.css:37–49`), but a large amount of the stylesheet hardcodes dark-only colors: `rgba(255,255,255,0.01..0.05)` tints, `#060810` video cell bg, `#0d1018` ROI canvas, `#9aa3bc` table cell text, `#333848` off-dot, `#1e2030` popover, `rgba(3,4,8,0.82)` modal scrim, `color-scheme: dark` on datetime inputs, scrollbar thumb, cam overlay fills. The light theme "works" only at a glance — once you scroll, it falls apart.
9. **Component duplication.** Several parallel patterns that do the same job:
    - Nav items: `.ttab`, `.ch-tab`, `.snav-item`, `.list-item` — four different looks.
    - Inputs: `.s-input`, `.filter-input`, `.grid-select`, `.api-input`, `.auth-input`, `.roi-point-row input` — same field, six classes.
    - Icon buttons: `.icon-btn`, `.icon-btn-sm`, `.param-help-btn`, `.entry-edit-btn`, `.entry-delete-btn`, `.compact-actions .icon-btn-sm`.
    - Modals: `.event-modal` and `.app-modal` — two scaffolds for the same job.
10. **Inline styles in `index.html`.** Dozens of `style="display:flex;gap:4px"`, `style="flex:1"`, `style="margin-top:0"`, `style="color:var(--danger);font-size:12px;..."` inside markup (e.g. `index.html:178, 465, 491–497, 557, 1017, 1021, 1046, 1054`). This is the clearest signal the design was added opportunistically, not from a system.
11. **Responsive behavior is minimal.** Only two breakpoints (`1180px`, `860px`) and they just shrink the side panel widths. The 58px left rail, the 272px obs-right panel, the multi-pill topbar, fixed column tables, and the `ch-layout` grid all stay the same down to phone widths. On real mobile, the journal table overflows horizontally, the settings sidebar eats half the screen, and the topbar pills wrap under the title.
12. **Touch targets below 40px.** `.icon-btn-sm` 26×26, `.ch-tab` 26–28px tall, `.param-help-btn` 14×14, `.entry-edit-btn` 24px, `.s-input` 32px, scrollbars 4px wide. Fails iOS/Android minimum 44px recommendation across the board.
13. **Data-density is over-tuned.** Table rows at `padding: 5px 10px`, event cards at `padding: 8px 10px`, settings rows min-height 38px with `6px` vertical padding. The app feels "busy" because nothing breathes.
14. **Empty states are weak.** `.video-grid:empty::after`, `.lists-empty-state`, `.empty-pane` — all a single uppercase mono line in `--text3`. No icon, no explanation, no CTA.
15. **Topbar overload.** Left: title. Center: clock. Right: CPU bar + RAM bar + channels pill + server pill + theme toggle. That's seven stacked information atoms in a 52px strip. Below ~1100px it wraps or clips.
16. **Video cell chrome is noisy.** Diagonal stripe background, radial gold glow, green neon detection boxes with blur, amber plate label with scale-bounce animation, scanning line on no-signal, pulsing live dot. Every cell is shouting. In a real surveillance product operators need the *event* to shout, not the cell frame.
17. **Password login has no show/hide, no caps-lock hint, no loading state, no error affordance beyond a red line.**
18. **`?` help buttons** are 14px circles rendered with a text "?" — they look like typos. They should be standard icon buttons with the `help-circle` glyph at a normal size.
19. **Settings page is a wall of rows.** No grouping beyond `s-card-header`, no section intros, no descriptions for the non-obvious knobs (there *is* a popover on `?`, but most users won't find it).
20. **The "Наблюдение" tab forces a fixed right-hand event feed at 272px** that cannot collapse, so on laptops the video grid gets squeezed, and on tablets the feed eats 40% of the screen.

**Verdict:** the system needs a design-token reset + a small but real component library (button, input, select, card, nav, modal, badge) + a proper mobile pass. The product is at a point where a visual refresh alone would not be enough — it needs a coherent system applied end-to-end.

---

## 2. Recommended visual direction

Targeted feel: calm professional operator tool (think Grafana / Linear / Tailscale admin), not "cyber dashboard".

**Typography**

- Body / UI: Inter (or keep DM Sans which is already linked) — humanist sans, 400 / 500 / 600.
- Monospace (numbers, plates, IDs, timestamps, logs): JetBrains Mono or keep Space Mono.
- Drop `Eexpresswayfree` from UI surfaces. Keep it — if at all — only for the plate label overlay on the video cell, where the license-plate look is intentional.
- Type scale (rem, base 14px):
  `xs 11px / sm 12px / base 14px / md 15px / lg 18px / xl 22px / 2xl 28px`.
- Line-heights: `1.4` body, `1.2` headings, `1` numeric badges.
- Letter-spacing: `0` default; `0.04em` only on tiny 11px labels; no uppercase except true section headers and badges.

**Spacing scale** (4px base): `2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 56`. Use tokens `--space-1 … --space-8`. Forbid raw pixel spacing inside components.

**Radius**: `--r-sm 6px`, `--r-md 8px`, `--r-lg 12px`, `--r-full 999px`. Pick one per component class and stop mixing.

**Shadows**: two levels only.

- `--shadow-1`: `0 1px 2px rgba(0,0,0,0.25)` — cards, popovers.
- `--shadow-2`: `0 12px 32px rgba(0,0,0,0.35)` — modals, menus.
- No glowing box-shadows on default states. Glow is reserved for *active event* and *alarm* affordances.

**Colors** (dark theme): near-black navy surfaces, one cool accent for interactive, gold reserved for matches/alarms.

- `--bg: #0b0d12`, `--surface: #12151c`, `--surface-raised: #171a23`, `--border: #232838`, `--border-strong: #2d3348`.
- Interactive accent (new): `--accent: #4c8cff` (or similar cool blue) — focus rings, primary CTAs, active nav.
- Alert/match accent: keep the gold `#e8a838` but use it **only** for plate-matched states, hot events, list alarms.
- Semantics: `--success #2ea865`, `--warning #e0a020`, `--danger #e24c4c`, `--info #4c8cff`.
- Text: `--fg-1 #e7ebf5`, `--fg-2 #9aa3bc`, `--fg-3 #5c6580`.

**Icon style**: one library, one weight. Lucide (24/24, stroke 1.5) is a good match. Stop mixing SVG source icons with text glyphs (`+`, `−`, `✕`, `?`, `◐`).

**Component behavior**

- Transitions: `120ms ease-out` for hover / focus; `180ms` for layout; no transforms on hover for buttons (no `translateY(-1px)`).
- Focus: visible 2px ring in `--accent`, inside `2px` offset. Keyboard focus must work on every interactive element.
- Hover: subtle bg change (`rgba(255,255,255,0.04)` dark / `rgba(0,0,0,0.04)` light), never border-color flashes to accent.
- Disabled: `opacity: .5`, `cursor: not-allowed`, no hover state.
- Loading: inline spinner in button, not a global curtain.

---

## 3. Theme rules

### 3.1 Dark theme principles

- Use layered surfaces (`bg < surface < surface-raised < modal`) to create hierarchy instead of relying on glow/borders.
- Borders always use `--border` tokens, never raw `rgba(255,255,255,*)`.
- Contrast minimum 4.5:1 for body text, 3:1 for labels ≥14px.
- Neon/glow only on: match alarm, live indicator, detection bounding box on video.
- Avoid pure black. `#0b0d12` keeps eye strain down on long shifts.

### 3.2 Light theme principles

- Background: soft neutral (`#f5f7fb`), surface white, border `#e2e6ef`.
- Text: `--fg-1 #13172a`, `--fg-2 #50596f`, `--fg-3 #8a93a8`.
- Accent stays the same hue but slightly darker for contrast: `--accent: #2f6be0`.
- Shadows become `rgba(16,22,40, .08)` — lighter, smaller blur.
- Scrim for modals: `rgba(16,22,40, .45)`.
- **No white-on-white video cells.** Give `video-cell` a dedicated `--video-bg` token that stays dark in both themes (operators expect black canvas behind video feeds).
- Status colors (success/warn/danger) need darker shades in light mode so they don't glow.

### 3.3 Shared tokens / components that must stay consistent across themes

- Radius, spacing, font scale, font families — identical.
- Component shape and sizing — identical (only colors swap).
- Icon set, icon weight — identical.
- Motion tokens (durations, easings) — identical.
- Status semantics — identical (success = green, warn = amber, danger = red, info = blue).
- License plate label: always dark bg + gold text — it's a domain affordance, not theme-driven.

---

## 4. Mobile / responsive rules

Target breakpoints: `sm 560, md 760, lg 1024, xl 1280, 2xl 1536`.

### 4.1 Layout adaptation

- **`sm` and below**: single-column stack. Hide the obs right panel by default; reveal via a floating "Events" button that opens a bottom sheet. Settings nav becomes a horizontal scrolling tab bar above the content.
- **`md`**: two-column with collapsible side panels. Video grid 1×N.
- **`lg`+**: current three-column model.

### 4.2 Sidebar / navigation behavior

- Below `md`: collapse the 58px left rail into a bottom tab bar (Obs / Journal / Lists / Settings) with user menu in a top-right avatar.
- Between `md`–`lg`: left rail stays at 58px, hover-expand disabled (touch-unfriendly).
- `lg`+: current hover-expand rail.

### 4.3 Tables and dense data blocks

- Journal and Lists tables: below `md`, switch to card-per-row layout. Each card shows plate (large, mono), time+channel (secondary row), country flag + direction badge (right side). Columns "Источник" and "Увер." move into a collapsed detail row.
- Fixed column widths removed below `lg`.
- Sticky header stays.

### 4.4 Touch targets

- Minimum hit area 44×44 for any control below `md`. Add an invisible padded hit region if the visible control is smaller.
- Scrollbars: `8px` on touch, `10px` thumb min.
- `.s-row input[type="checkbox"]` toggle: enlarge to 44×26 below `md`.
- `.param-help-btn` becomes a standard 32×32 icon button with proper icon.

### 4.5 Spacing and typography on small screens

- Base font size bumps from 14 to 15px below `md` for readability.
- Section padding doubles (e.g., settings card `16px` → `20px`).
- Settings row labels stack above inputs instead of 180px side column.
- Filter card: stacks to full-width fields, "Найти" / "Сброс" / "Экспорт" become a bottom sticky action row.

---

## 5. Task list

Format per task:

- **Problem** — what is wrong today, with evidence.
- **Proposed change** — what to do.
- **Why** — user/product value.
- **Priority** — High / Medium / Low.
- **Acceptance** — how we know it's done.
- **Files** — primary places to edit.

Tasks are grouped. Each group header notes whether tasks in it are **quick wins** or **larger redesign** work.

---

### 5.A Global design system (larger redesign)

#### ✅ G1. Introduce a real type system and drop single-font usage
- **Problem**: `--mono` and `--sans` both point to `Eexpresswayfree`; DM Sans is linked but unused; font-sizes are hardcoded pixels across `styles.css`.
- **Change**: Add two font stacks — humanist sans (Inter or DM Sans) for UI, monospace (JetBrains Mono or Space Mono) for data. Introduce tokens `--font-sans`, `--font-mono`, `--fs-xs … --fs-2xl`, `--lh-*`, `--tracking-*`. Replace every raw `font-size: Npx` with a token.
- **Why**: single biggest lever for "looks human-designed". Restores hierarchy.
- **Priority**: High.
- **Acceptance**: no raw `font-size: *px` in stylesheet; body reads at ≥13px; headings, labels, values all use distinct type tokens.
- **Files**: `app/web/styles.css` (token section + all rules), `app/web/index.html` (font `<link>`).

#### ✅ G2. Replace the color system
- **Problem**: gold is everywhere; no cool interactive accent; light theme only flips a handful of tokens.
- **Change**: Introduce new token groups per section 2. Reassign `--accent` to blue for interactive use; reserve gold for "alarm/match/hot" states only. Define `--video-bg` fixed-dark token.
- **Why**: quieter UI, clearer semantics, working light theme.
- **Priority**: High.
- **Acceptance**: primary button is blue; focus rings are blue; gold only appears on plate matches and list alarms; no raw hex outside the token block.
- **Files**: `app/web/styles.css` (`:root` + theme block + downstream).

#### ✅ G3. Collapse parallel component patterns
- **Problem**: four nav patterns, six input classes, five icon buttons, two modal scaffolds (section 1, item 9).
- **Change**: Define a single `.input`, `.btn`, `.icon-btn`, `.nav-item`, `.card`, `.modal`, `.badge`. Re-express `.s-input`, `.filter-input`, `.grid-select`, `.api-input`, `.auth-input` as a single base. Same for nav items.
- **Why**: smaller stylesheet, consistent behavior, easier future changes.
- **Priority**: High.
- **Acceptance**: one rule per primitive; no `!important` overrides of primitives; visual regression parity in both tabs.
- **Files**: `app/web/styles.css`, `app/web/index.html` (classname swaps).

#### ✅ G4. Extract all inline styles from `index.html`
- **Problem**: ≥30 inline `style="…"` attributes in markup (`index.html:178, 465, 491, 557, 1017, 1021, 1046, 1054, 1141, 1161 …`).
- **Change**: Move each into a semantic utility or component class. Introduce a minimal utility layer (`.stack`, `.cluster`, `.flex-1`, `.hidden`, `.w-full`) if needed.
- **Why**: every inline style is a design-system bypass.
- **Priority**: Medium.
- **Acceptance**: no `style=` in `index.html` except runtime-toggled display:none handled via `hidden` attr or a `.is-hidden` class.
- **Files**: `app/web/index.html`, `app/web/styles.css`.

#### ✅ G5. Radius, spacing, shadow tokens — enforced
- **Problem**: radii `3,5,6,7,8,10,11,14,99` and spacings `4,5,6,7,8,9,10,12,14` used raw.
- **Change**: Use only `--r-sm/md/lg/full` and `--space-1…8`. Remove one-off values.
- **Why**: visual rhythm.
- **Priority**: Medium.
- **Acceptance**: grep for `border-radius: \d+px` returns zero in component rules.
- **Files**: `app/web/styles.css`.

---

### 5.B Navigation (quick wins + redesign)

#### ✅ N1. Rebuild the left rail
- **Problem**: 58px rail with hover-expand, active `::before` notch, gold active-state, no mobile behavior. The hover-expand animation feels gimmicky and the 58px collapsed state wastes space on mobile.
- **Change**: Keep 56px rail on `lg`+. On `md` and below convert into a 4-item bottom tab bar. Drop the `::before` accent notch in favor of a filled rounded background on active. Use blue accent, not gold.
- **Why**: mobile becomes usable; visual noise drops.
- **Priority**: High.
- **Acceptance**: on 375px viewport, rail is at bottom, 64px tall, thumb-reachable; on desktop, rail active state has no notch.
- **Files**: `index.html` (`.left-rail`), `styles.css` (`.left-rail`, `.ttab*`).

#### ✅ N2. Topbar declutter (desktop grouping done)
- **Problem**: 7 info atoms in a 52px strip (section 1, item 15). On `md` it wraps or overlaps.
- **Change**: On `lg`+: title | clock | (CPU+RAM grouped into a single "health" compact widget) | status pill | user. On `md` and below: title + status pill + overflow menu (CPU/RAM/server behind a "⋯" button). Theme toggle moves into user menu.
- **Why**: one glance = one status.
- **Priority**: High.
- **Acceptance**: topbar fits in 52px at 360px viewport; no wrap or clipping down to 320px.
- **Files**: `index.html` (topbar block), `styles.css` (`.topbar*`).

#### ✅ N3. Settings nav becomes horizontal on mobile
- **Problem**: 210px `.settings-nav` sidebar on a 375px screen eats 56% of width.
- **Change**: Below `md`, convert `.settings-nav` into a horizontally scrollable pill bar pinned under topbar; content fills below.
- **Why**: settings become usable on phones.
- **Priority**: Medium.
- **Acceptance**: on 375px, nav is one row, scrollable; content area ≥85% width.
- **Files**: `styles.css` (`#tab-settings`, `.settings-nav`).

---

### 5.C Forms, inputs, selects (quick wins)

#### F1. Unify input primitive
- **Problem**: six classes for the same `<input>`. Different heights (28, 30, 32, 36), different focus behavior, different paddings.
- **Change**: One `.input` with modifier sizes `--sm/--md/--lg`. Single focus ring. Single disabled state. Selects use the same base plus a chevron utility.
- **Why**: consistent forms everywhere.
- **Priority**: High.
- **Acceptance**: all `<input>` / `<select>` / `<textarea>` render with the same visual language.
- **Files**: `styles.css`, `index.html`.

#### F2. Labels above, not in 180px side column
- **Problem**: `.s-row-label` fixed at 180px; long labels truncate with ellipsis (`styles.css:1120`), losing meaning.
- **Change**: Stack label above input by default. Keep two-column only when the whole row has room (use `.s-row--inline` variant).
- **Why**: no truncation, better mobile, clearer scanning.
- **Priority**: Medium.
- **Acceptance**: no label is clipped on any screen width.
- **Files**: `styles.css` (`.s-row*`), `index.html`.

#### ✅ F3. Replace the `?` text button with a real help icon
- **Problem**: 14px circle with text "?" (`styles.css:1125`). Looks unintentional.
- **Change**: Use a proper `help-circle` icon inside an `.icon-btn` (20×20 glyph, 32×32 hit area). Keep the existing popover behavior.
- **Why**: looks like a feature, not a typo.
- **Priority**: Medium.
- **Acceptance**: help trigger visually matches other icon buttons; still opens the popover with the existing `data-help` key.
- **Files**: `index.html` (all `param-help-btn` occurrences), `styles.css`, `app/web/js/settings.js` (if selector changes).

#### F4. Toggle switch uses design-system colors and size
- **Problem**: toggle is gold-checked (`styles.css:654`), mixes with primary button language.
- **Change**: Use `--accent` (blue) for `:checked`. Increase touch size below `md` to 44×26. Share the base class with any future toggle.
- **Why**: consistent with new accent system; better touch.
- **Priority**: Low.
- **Acceptance**: checked toggles are blue; 44px tall on mobile.
- **Files**: `styles.css`.

#### F5. Login overlay — visibility toggle, caps hint, loading state
- **Problem**: `#login-overlay` has login + password + error + button only.
- **Change**: Add eye-toggle on password, caps-lock hint, spinner in button during auth. Brand the card header with the product name, not just "Вход в систему".
- **Why**: reduces failed logins, looks like a real product.
- **Priority**: Medium.
- **Acceptance**: caps lock triggers a hint; button shows spinner while `POST /api/auth/login` is in flight.
- **Files**: `index.html` (`#login-overlay`), `styles.css`, `app/web/js/app.js` (auth flow).

---

### 5.D Tables (quick wins + redesign)

#### T1. Relax data density
- **Problem**: rows at `padding: 5px 10px` with 10–11px text.
- **Change**: Rows at `padding: 10px 14px`, body font 13px, zebra off (hover only). Header 11px/0.06em tracking (not `0.1em` uppercase).
- **Why**: scannable.
- **Priority**: Medium.
- **Acceptance**: row height ~40px; no truncation of plate column.
- **Files**: `styles.css` (`.data-table*`).

#### T2. Card-per-row layout on mobile
- **Problem**: fixed column widths overflow on phones.
- **Change**: Below `md`, render each table row as a card via CSS grid (`.data-table--stacked`) showing plate + time/channel + direction badge. Hide non-critical columns behind an expand chevron.
- **Why**: journal usable on phone.
- **Priority**: Medium.
- **Acceptance**: journal and lists tables readable at 360px width with no horizontal scroll.
- **Files**: `styles.css`, possibly small changes in `app/web/js/journal.js`, `app/web/js/lists.js`.

#### ✅ T3. Drop the left-border amber glow on list-matched rows
- **Problem**: `tr.list-white/.list-black/.list-info` rows get amber background (`styles.css:1329–1333`) even though the border indicates color. The background + glow combine into a muddy highlight.
- **Change**: Keep the 3px inset left border in list color (white/red/green). Remove the amber glow background. Use a 6% tint of the list color instead for the row bg.
- **Why**: each list type reads as its own semantic, not "gold match".
- **Priority**: Medium.
- **Acceptance**: black-list rows are subtly red-tinted, white-list rows subtly neutral, info rows subtly green. No gold backdrop.
- **Files**: `styles.css`.

---

### 5.E Cards and panels (quick wins)

#### ✅ C1. Remove the gold left accent on every `s-card-header`
- **Problem**: `styles.css:826` forces `border-left: 3px solid rgba(232,168,56,0.22)` on every section header. Every single card in Settings looks alarm-adjacent.
- **Change**: Drop that rule. Differentiate section headers with weight/size, not color.
- **Why**: calmer Settings; reserve gold for real alerts.
- **Priority**: High (quick win).
- **Acceptance**: no `border-left` on `s-card-header`.
- **Files**: `styles.css`.

#### ✅ C2. Card header typography reset
- **Problem**: 10px uppercase letter-spaced — unreadable.
- **Change**: 13px medium, sentence case. Keep a small uppercase eyebrow only if used as a section label above a large header.
- **Why**: hierarchy.
- **Priority**: High.
- **Files**: `styles.css` (`.s-card-header`, `.panel-header`).

#### C3. Debug / log panel visual reset
- **Problem**: log panel inherits dashboard noise (HUD borders, uppercase header, gold sheen).
- **Change**: Flat surface, mono body, quiet border. Header line uses normal case + muted fg.
- **Why**: logs should read like logs, not decorations.
- **Priority**: Low.
- **Files**: `styles.css` (`.obs-debug-panel`, `.log-*`).

---

### 5.F Modals (quick wins)

#### M1. Merge `.event-modal` and `.app-modal`
- **Problem**: two modal scaffolds. Slight size and padding differences.
- **Change**: Single `.modal` scaffold with size variants (`--sm/--md/--lg/--xl`). `event-modal` becomes `.modal--xl`.
- **Why**: consistency.
- **Priority**: Medium.
- **Files**: `styles.css`, `index.html`, `app/web/js/events.js`.

#### ✅ M2. Scrim and entry animation
- **Problem**: modal-in animation uses a spring-bounce `cubic-bezier(0.34, 1.56, 0.64, 1)` scale — playful, wrong tone for a destructive confirm dialog.
- **Change**: `opacity 160ms ease-out` + `transform: translateY(8px) → 0`. No bounce.
- **Why**: production feel.
- **Priority**: Low.
- **Files**: `styles.css`.

#### ✅ M3. Modal header: use sentence-case title
- **Problem**: modal heads use uppercase mono 10px.
- **Change**: 15px semibold sentence case. Keep close button on the right.
- **Why**: clarity.
- **Priority**: Medium.
- **Files**: `styles.css` (`.app-modal-head`, `.event-modal-head`).

---

### 5.G Buttons (quick wins)

#### ✅ B1. Flatten the primary button
- **Problem**: gold gradient + inset highlight + outer glow + hover `translateY(-1px)` (`styles.css:537–546`).
- **Change**: Solid `--accent` (blue). No gradient. No transform. 2px focus ring. Disabled `.5` opacity.
- **Why**: removes "gamified" feel.
- **Priority**: High (quick win).
- **Files**: `styles.css` (`.btn-primary`).

#### ✅ B2. Ghost button
- **Problem**: hover turns border gold + bg gold glow. Every secondary action feels primary.
- **Change**: Hover = `bg: rgba(255,255,255,0.04)`, border unchanged, fg `--fg-1`. Active = slightly darker bg.
- **Priority**: High.
- **Files**: `styles.css` (`.btn-ghost`).

#### ✅ B3. Danger button consistency
- **Problem**: danger button uses gradient + transform, matching primary's gamified style.
- **Change**: Solid `--danger`, no gradient, no transform.
- **Priority**: Medium.
- **Files**: `styles.css` (`.btn-danger`).

#### B4. Size system
- **Problem**: heights 24/26/28/30/32/36/42 scattered.
- **Change**: Button sizes `--sm 28`, `--md 36`, `--lg 44`. Use `--md` default, `--lg` on mobile for primary actions.
- **Priority**: Medium.
- **Files**: `styles.css`.

---

### 5.H Empty states (quick wins)

#### E1. Give every empty state an icon + message + CTA
- **Problem**: `.lists-empty-state`, `.empty-pane`, `.video-grid:empty::after`, `#channelConfigEmpty`, `#controllerConfigEmpty`, `#userConfigEmpty` all render as a single muted mono line.
- **Change**: Each empty state = centered icon (48px, muted) + short title (15px medium) + one-line explanation (13px) + primary CTA button where applicable (e.g., "Создать канал", "Новый список", "Добавить пользователя").
- **Why**: guides first-time users; makes the app feel finished.
- **Priority**: Medium.
- **Files**: `index.html` (all empty blocks), `styles.css`, per-tab JS modules to wire CTAs to the existing create flows.

---

### 5.I Alerts and toasts (quick win)

#### A1. Toast system
- **Problem**: `.app-toast` exists but only handles success (green, mono, uppercase letter-spaced).
- **Change**: Four variants (success/info/warning/error) with icon + title + optional description. Bottom-right stack on desktop, bottom-center on mobile. Auto-dismiss 4s for success, sticky for error until user closes.
- **Why**: real feedback system.
- **Priority**: Medium.
- **Files**: `styles.css`, `app/web/js/ui.js` (toast helper).

---

### 5.J Dark theme fixes (quick wins)

#### DK1. Remove raw `rgba(255,255,255,*)` from rules
- **Problem**: dozens of such values for borders, separators, row hover, card header tints.
- **Change**: Replace with `--border`, `--border-strong`, `--hover-bg`, `--row-divider` tokens.
- **Why**: makes light theme possible.
- **Priority**: High.
- **Files**: `styles.css` global.

#### ✅ DK2. Remove HUD noise from video cells
- **Problem**: diagonal-stripe background + radial gold glow on every `.video-cell` (`styles.css:384–388`) + scanning line on no-signal + pulsing live dot.
- **Change**: Flat dark canvas. Keep live dot (simpler, no pulse by default — pulse only on active detection). Drop the striped background entirely. Drop the scanning line.
- **Why**: operators need to focus on the frame, not the chrome.
- **Priority**: Medium.
- **Files**: `styles.css` (`.video-cell*`, `.cam-*`).

---

### 5.K Light theme (larger redesign)

#### LT1. Full light-theme audit and rewrite
- **Problem**: light theme is broken (section 1, item 8).
- **Change**: After DK1 is done, add a real `body[data-theme="light"]` override:
    - `--bg:#f5f7fb; --surface:#ffffff; --surface-raised:#ffffff`
    - `--border:#e2e6ef; --border-strong:#d0d6e4`
    - `--fg-1:#13172a; --fg-2:#50596f; --fg-3:#8a93a8`
    - `--accent:#2f6be0; --success:#188a4a; --warning:#b8860b; --danger:#c43030`
    - `--hover-bg:rgba(16,22,40,.04); --row-divider:rgba(16,22,40,.06)`
    - `--modal-scrim:rgba(16,22,40,.45)`
    - `--video-bg:#0b0d12` (forced dark)
- Also: `datetime-local` inputs need `color-scheme: light`; scrollbar thumb retinted; any hardcoded hex (`#060810`, `#0d1018`, `#9aa3bc`, `#333848`, `#1e2030`) replaced with tokens.
- **Why**: light theme is currently a marketing claim, not a feature.
- **Priority**: High.
- **Acceptance**: every page, every modal, every panel renders correctly in light theme; screenshot each tab for parity.
- **Files**: `styles.css`, `index.html` (scheme hints), possibly `app/web/js/state.js` (theme persistence already present per memory).

#### LT2. Status colors darken in light mode
- **Problem**: neon greens/reds that glow on dark look washed-out or aggressive on light.
- **Change**: Per-theme tokens for `--success/--warning/--danger` with darker lightness in light mode.
- **Priority**: Medium.
- **Files**: `styles.css`.

---

### 5.L Mobile / responsive pass (larger redesign)

#### R1. Breakpoint + layout system
- **Problem**: two shallow breakpoints (`1180`, `860`).
- **Change**: Adopt `sm 560, md 760, lg 1024, xl 1280`. Define container queries where it helps (`obs-right`, `lists-sidebar`, `settings-nav`).
- **Priority**: High.
- **Files**: `styles.css`.

#### R2. Observation tab mobile layout
- **Problem**: 272px right events panel always visible; grid selector stuck in desktop layout.
- **Change**: Below `md`, hide events panel; add a floating button "События ({count})" that opens a bottom sheet. Grid selector becomes a chip-style pill row (1×1 / 2×2 / 2×3 / 3×3).
- **Priority**: High.
- **Files**: `styles.css`, `app/web/js/video-grid.js`, `app/web/js/events.js`.

#### R3. Lists tab mobile layout
- **Problem**: 230px sidebar + table side-by-side. On phone, neither is usable.
- **Change**: Below `md`, show the sidebar as a drawer, content area fills. Entry table becomes stacked cards (T2).
- **Priority**: High.
- **Files**: `styles.css`, `index.html`, `app/web/js/lists.js`.

#### R4. Settings tab mobile layout
- **Problem**: same sidebar+content issue; inline labels break.
- **Change**: N3 (horizontal pills) + F2 (stacked labels) combined.
- **Priority**: High.
- **Files**: `styles.css`, `index.html`.

#### R5. Channel config on mobile
- **Problem**: `channelTabs` row wraps ugly; vision tab has two inner panels that don't fit below `md`.
- **Change**: Channel tabs become a horizontal scrollable pill row. Vision tab stacks: canvas on top, controls below. ROI/size list becomes collapsible groups.
- **Priority**: Medium.
- **Files**: `styles.css`, `index.html`.

#### R6. Touch target sweep
- **Problem**: section 1, item 12 — many controls below 44px.
- **Change**: Enforce min 44×44 hit area below `md` for every clickable. Achieve it via padding where the visual control is smaller.
- **Priority**: High.
- **Files**: `styles.css`.

---

### 5.M Page-specific (mixed)

#### P1. Observation — quieter video cell chrome (also DK2)
- Already covered; priority High.

#### P2. Observation — event feed card redesign
- **Problem**: `.ev-item` has 3-column grid with flag + plate + meta, small hover translate, multiple colors competing. The `.ev-item.hot` state adds an amber backdrop on top of the list-type inset borders — double signal.
- **Change**: Clean 3-row structure: (1) plate large mono; (2) channel · time; (3) confidence + direction badges on right. Hot state = only left inset accent, no backdrop change.
- **Priority**: Medium.
- **Files**: `styles.css` (`.ev-*`), `app/web/js/events.js`.

#### P3. Journal — filter card
- **Problem**: filters wrap weirdly; "Экспорт" button has icon + text mis-aligned via inline styles.
- **Change**: Grid-based filter card (`repeat(auto-fit, minmax(180px, 1fr))`) with a sticky action bar at the end. On mobile, single column with sticky action row.
- **Priority**: Medium.
- **Files**: `styles.css`, `index.html`.

#### ✅ P4. Lists sidebar header
- **Problem**: "СПИСКИ НОМЕРОВ" uppercase header with + / − tiny buttons crammed inside.
- **Change**: Sentence-case title, + button to the right as a full icon button, rename − to a proper delete icon and make it conditional (only visible when a list is selected).
- **Priority**: Medium.
- **Files**: `index.html`, `styles.css`.

#### P5. Settings — general tab section intros
- **Problem**: wall of rows; no explanation for what a section does.
- **Change**: Add a 1-sentence description under each `s-card-header`. Group related sections under H2-level dividers ("Интерфейс", "Обработка видео", "Данные", "Служебное").
- **Priority**: Low.
- **Files**: `index.html`.

#### P6. Settings — users
- **Problem**: create and edit forms live as two separate panes with `display:none`; error text is inline-styled.
- **Change**: Unify into one form component. Error line becomes a shared `.form-error` class.
- **Priority**: Low.
- **Files**: `index.html`, `styles.css`, `app/web/js/users.js`.

#### P7. Event modal layout
- **Problem**: `2fr / 1fr` grid fixed; on phones the frame image shrinks below 200px min and meta list becomes narrow.
- **Change**: Stack vertically below `md` (frame, plate image, meta). Cap image max-height at 60vh on mobile.
- **Priority**: Medium.
- **Files**: `styles.css` (`.event-modal-body`).

#### P8. Auth card branding
- **Problem**: plain "Вход в систему" mono header.
- **Change**: Add product logo (reuse favicon) above the title; title becomes sentence case. Small tagline below (e.g., "ANPR operator console").
- **Priority**: Low.
- **Files**: `index.html`, `styles.css`.

---

## 6. Quick wins vs larger redesign

**Quick wins** (can land in a short pass, big visible impact):
C1, C2, B1, B2, B3, F3, DK2, T3, N2 (desktop-only part), M2, M3, P4, G5.

**Larger redesign** (require a system reset, touching many files):
G1, G2, G3, G4, LT1, R1, R2, R3, R4, N1 (mobile rail), T2.

**Recommended order**:

1. G1 + G2 + G5 (design tokens reset) — unlocks everything else.
2. G3 + G4 (primitive consolidation + inline-style extraction).
3. Quick-win batch (C1, C2, B1–B3, F3, DK2, T3).
4. LT1 + DK1 (light theme becomes real).
5. R1 → R6 (mobile pass).
6. Page-specific P1–P8.

---

## 7. Out of scope / to revisit later

- Branding work (logo, wordmark, color of the login hero) — depends on product direction.
- Iconography custom set — use Lucide for now; commission custom icons only after the system is stable.
- Onboarding / first-run tour — not addressed here; plug in after empty-state redesign (E1).
- Keyboard shortcuts overlay — worth having, but belongs in its own UX pass.
- Accessibility audit (ARIA roles, live regions for the event feed, screen-reader labels) — called out here as a known gap; needs a dedicated task list after the visual reset.
