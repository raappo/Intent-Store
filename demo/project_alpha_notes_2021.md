# Project Alpha — Q3 2021 Sprint Notes
## Meeting: 2021-07-14  (recorded by R. Nakamura)

### Attendees
- Rachel Nakamura (PM)
- Dev Kapoor (Lead Eng)
- Sofia Brandt (UX)

### Action Items from Last Sprint
- [DONE] Migrate CI from Jenkins to GitHub Actions (Dev)
- [DONE] Wireframes for onboarding flow v2 (Sofia)
- [STALE] API contract with partner team — no update received

### This Sprint Goals
1. Implement user analytics pipeline (Mixpanel → BigQuery)
2. A/B test the revised onboarding flow
3. Fix flaky test suite (currently ~12% flake rate)

### Discussion Notes
Dev noted that the current database schema will need a migration before Q4
because the users.preferences column is at capacity.  We agreed to add a
JSONB column in the next non-breaking release window.

Sofia presented two variants for the new empty-state illustration.
Team voted for Option B (the "rocket" motif) 7-2.

### Risks
- Partner API dependency is blocking story #PRJ-449
- Flaky tests are causing false CI failures ≈ 1–2x per day

### Next meeting
2021-07-28 at 10:00 AM PST
