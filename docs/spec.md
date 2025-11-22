# ShiftGuard - Phase 1 Logic Specification

## Context

ShiftGuard is a compliant-by-design scheduler for Canadian businesses. It ingests availability from Google Forms, generates a schedule respecting labor laws (BC/Ontario), and publishes to Google Calendar.

## Core Python Functions

### 1. `ingest_availability(payload: dict) -> bool`

**Goal:** Process incoming Webhook data from Google Forms.
**Logic:**

1. Extract email from the payload.
2. Lookup `employee_id` from the `employees` table using the email.
    * *Error Handling:* If email not found, log error and return False (do not create phantom employees).
3. Parse availability dates and preferences.
4. Perform an `UPSERT` on the `availability` table (Update if exists, Insert if new) to ensure the latest form submission is the source of truth.

### 2. `generate_draft_schedule(start_date: date, end_date: date) -> List[Shift]`

**Goal:** Create a valid schedule while flagging compliance risks.
**Logic:**

1. **Fetch Data:** Get all `availability` for the date range and all `shifts` from the *previous* 24 hours (to check for clopening).
2. **Requirement Loop:** Iterate through the "Shift Requirements" (Hardcoded config for MVP: e.g., "Sat: 2 Openers, 2 Closers").
3. **Candidate Selection:** For each slot, filter employees who `can_open` or `can_close`.
4. **Constraint Check (The "Lawyer" Filter):**
    * **Rule A (Rest Period):** Calculate `time_since_last_shift`. If < 8 hours, Mark as `VIOLATION_RISK`.
    * **Rule B (Weekly Rest):** Check if employee has had 32 consecutive hours off in the current week.
5. **Allocation:** Assign the shift to the employee with the fewest hours so far (Fairness).
6. **Persistence:** Save rows to `shifts` table with `status='DRAFT'`.

### 3. `publish_to_calendar(start_date: date, end_date: date) -> Dict[str, int]`

**Goal:** Push approved shifts to Google Calendar using Composio.
**Logic:**

1. **Query:** Select all shifts where `status='PUBLISHED'` and `start_time` is within range.
2. **Tool Call:** Use `composio_core` to call Google Calendar.
    * *Action:* `calendar_create_event`
    * *Attendees:* `[employee_email]`
    * *Description:* "Please Accept/Decline within 24 hours."
3. **Update State:** Upon success, update database `status` -> 'AWAITING_RESPONSE'.
4. **Return:** Summary of invites sent (e.g., `{"sent": 15, "failed": 0}`).

## Tech Stack Definitions

* **Database Driver:** `psycopg2-binary` (Standard for Postgres).
* **Agent Tooling:** `composio-core` (For Calendar/Gmail integrations).
* **Web Server:** `Flask` (Lightweight, stateless for Vercel).
