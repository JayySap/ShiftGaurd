# 🛡️ ShiftGuard

## Compliant-by-Design Scheduler for Canadian Businesses

### Automated Roster Management • BC Labor Law Enforcement • Serverless Architecture**

![Python](https://img.shields.io/badge/Python-3.11-blue) ![Vercel](https://img.shields.io/badge/Deployed_on-Vercel-black) ![Postgres](https://img.shields.io/badge/Database-Neon_Serverless-green) ![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-red)

## 📖 Overview

ShiftGuard is a headless, serverless scheduling engine designed to automate workforce management for retail and service businesses. Unlike standard scheduling tools, ShiftGuard is **compliance-aware**. It programmatically enforces British Columbia labor laws (e.g., minimum rest periods, split shift rules) before a schedule is ever drafted.

It replaces the chaotic "Spreadsheet + Text Message" workflow with a streamlined loop: **Google Forms (Input) → Python Logic (Process) → Google Calendar (Output).**

## 🏗️ Architecture

ShiftGuard operates on a fully serverless stack to minimize costs and maintenance.

```mermaid
graph LR
    A[Staff Input] -- Google Forms --> B(Webhook / Vercel)
    B --> C[(Neon Postgres)]
    D[Cron Job] -- Trigger --> E{Scheduler Engine}
    E -- Read Rules --> C
    E -- Write Draft --> C
    F[Manager] -- Review/Publish --> G[Streamlit Dashboard]
    G -- API Call --> H[Composio Publisher]
    H -- API --> I[Google Calendar]
```

### Tech Stack

**Backend**: Python (Flask), hosted on Vercel Serverless Functions.

**Database**: Neon (Serverless PostgreSQL) with psycopg2 connection pooling optimized for lambda environments.

**Frontend**: Streamlit (Admin Command Center) with Plotly for Gantt chart visualization.

**Integrations**:

- Composio: Manages OAuth2 handshake and API calls for Google Calendar.
- Google Apps Script: Custom webhook to parse Form data into JSON.

**DevOps**: Poetry (Dependency Management), GitHub Actions (CI/CD).

## ⚡ Key Features

### 1. The Compliance Engine

The core value of ShiftGuard is its refusal to generate illegal schedules.

- **The "Clopening" Guard**: Automatically flags or blocks shifts where an employee closes (e.g., ends at 10 PM) and opens the next day (e.g., starts at 6 AM) with less than 8 hours of rest (BC Employment Standards Act).
- **Role Coverage**: Ensures a "Shift Lead" is present during all operating hours.
- **Break Calculations**: Automatically appends legally required paid/unpaid breaks based on shift length (>5hrs vs >7hrs).

### 2. "Set & Forget" Recurring Availability

Employees define their "Standard Week" (e.g., "I can Open on Mondays, Close on Tuesdays").

The system uses these rules to generate fresh schedules weekly without requiring weekly form submissions.

### 3. Smart Allocation Logic

The scheduler uses a priority-waterfall algorithm to ensure fairness and coverage:

- **Mid-Shift Specialists**: Assigned first to hard-to-fill midday slots.
- **Restricted Staff**: Assigned to their specific Open/Close windows.
- **Flexible Staff ("Heroes")**: Used to fill remaining gaps and manage overflow.

### 4. Google Forms Integration

Employees submit availability changes via Google Form. A webhook processes responses and updates the `standard_availability` table, enabling self-service availability management without admin overhead.

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- Poetry
- A Vercel Account
- A Google Cloud Project (for Calendar API)

### Installation

## Clone the Repository

```bash
git clone https://github.com/yourusername/ShiftGuard.git
cd ShiftGuard
```

## Install Dependencies

```bash
poetry install
```

## Environment Setup

Create a `.env` file based on `.env.example`:

```bash
DATABASE_URL="postgres://user:pass@ep-server.neon.tech/neondb"
COMPOSIO_API_KEY="your_key_here"
GOOGLE_CALENDAR_ID="your_calendar_id"
FLASK_SECRET_KEY="random_string"
CRON_SECRET="secure_hex_string"
```

## Database Migration

Initialize the schema and seed test data:

```bash
poetry run python -c "from dotenv import load_dotenv; load_dotenv(); from src.database import init_db, get_db_cursor; init_db(); cur = get_db_cursor(commit=True).__enter__(); cur.execute(open('database/seed.sql').read())"
```

### Running Locally

**Start the API:**

```bash
poetry run python -m src.app
```

**Start the Dashboard:**

```bash
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

## 🛠️ Usage Workflow

1. **Ingestion**: Staff submits the "Weekly Availability" Google Form. Google Apps Script triggers the `/api/v1/availability/webhook` endpoint.

2. **Generation**: Every Friday at 5:00 PM, a Vercel Cron Job triggers `/api/v1/schedule/generate`.

3. **Review**: The Manager opens the Streamlit Dashboard to visualize the timeline. Violations appear in RED.

4. **Publishing**: The Manager clicks "Publish". The API batches requests (5 at a time) to avoid Vercel timeouts and pushes invites to staff calendars via Composio.

## 📊 API Endpoints

### Generate Schedule

```bash
POST /api/v1/schedule/generate
Authorization: Bearer <CRON_SECRET>
{
  "start_date": "2025-01-06",
  "end_date": "2025-01-12"
}
```

### Publish Shifts (Batched)

```bash
POST /api/v1/schedule/publish
{
  "batch_size": 5
}
```

Returns `{published, failed, remaining}`. Keep calling until `remaining == 0`.

### Get Shifts

```bash
GET /api/v1/shifts?start_date=2025-01-06&end_date=2025-01-12&status=DRAFT
```

### Get Employees

```bash
GET /api/v1/employees
```

## 🧠 Technical Challenges Solved

**Serverless Connection Pooling**: Implemented a custom database connection strategy to handle Vercel's ephemeral environment, preventing "Too Many Connections" errors on Neon.

**Idempotent Publishing**: The publisher logic is designed to be fail-safe. It can be re-run multiple times; it checks shift status before sending invites to prevent duplicate calendar events.

**Headless Authentication**: Used a `CRON_SECRET` bearer token pattern to secure internal API endpoints without requiring a full auth server.

**Composio SDK Threading Bug**: Monkey-patched the SDK to disable thread safety checks that were incompatible with serverless execution.

**Query String Handling**: Fixed Vercel/Flask proxy incompatibility by embedding query parameters directly in the path URL.

## 🎨 Dashboard Features

The Streamlit dashboard provides:

- **Gantt Timeline View**: Visual representation of daily schedules with color-coded shift types (OPEN=blue, MID=gold, COVER=gold, CLOSE=red)
- **Day Selector**: Navigate through the week to inspect coverage
- **Generate Schedule Button**: One-click schedule creation with date range defaults
- **Publish All Button**: Batched publishing with progress bar
- **Violations Table**: Highlights compliance issues requiring manager review
- **Employee Roster**: Weekly availability breakdown and role classification

## 📁 Project Structure

```bash
src/
  api/routes.py          - Flask endpoints
  services/scheduler.py  - Core scheduling logic
  services/calendar.py   - Google Calendar publisher
  config.py              - Shift hours, requirements
  database.py            - Postgres connection pool
dashboard/
  app.py                 - Streamlit UI
database/
  schema.sql             - Table definitions
  seed.sql               - Test data
tests/
  test_recurring_scheduler.py  - Generates and prints a week
```

## 🔧 Customizing for Your Business

Edit `src/config.py` to change:

- Shift start/end times
- Number of shifts per day
- Daily staffing requirements
- Which shifts require supervisors

The scheduler will adapt to whatever shift structure you define.

## 📄 License

MIT

Built with ❤️ in Victoria, BC.
