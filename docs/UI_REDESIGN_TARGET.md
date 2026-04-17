# UI redesign target

Primary visual reference:
- docs/anpr-clean-dashboard-concept.tsx

Goal:
Implement a real redesign of the existing ANPR web UI so it becomes closer to a modern, minimal, professional operator dashboard.

Priority:
1. Observation
2. Settings
3. Journal
4. Clients
5. Zones

## Observation
Must visibly move away from the legacy layout.
Keep:
- video grid
- grid size switcher
- right events panel
- event detail modal
- superadmin-only logs/debug area

Required direction:
- cleaner overall composition
- framed camera area inside a proper panel
- more refined right event column
- logs as a secondary technical panel
- remove the feeling of large dead empty space
- not just recolor the old screen

## Journal
- cleaner filter toolbar
- improved table hierarchy
- stronger plate column emphasis
- better spacing and readability

## Zones
- cleaner split layout
- left list + right details
- modern modal styling

## Clients
Keep current project logic:
- client is separate
- list is separate
- client can be attached to lists

UI structure:
- Clients subtab
- Lists subtab

Do not create a separate Bindings tab.

## Settings
Keep real sections:
- General
- Channels
- Controllers
- Users
- System Data
- Debug

Inside Channels:
- Channel
- OCR
- Motion
- Controller

Direction:
- clearer section hierarchy
- more polished forms
- cleaner side navigation
- denser but more readable technical UI