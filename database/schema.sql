-- ShiftGuard Schema - Phase 1 MVP
-- Optimized for Neon Postgres & Canadian Labor Law Compliance

-- Enable UUID extension for secure IDs
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. EMPLOYEES
-- Stores core staff data and legal waivers
CREATE TABLE employees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone_number TEXT,
    role TEXT NOT NULL DEFAULT 'Staff', -- e.g., 'Barista', 'Shift Lead'

    -- COMPLIANCE FLAGS
    max_weekly_hours INTEGER DEFAULT 40,
    waived_notice_period BOOLEAN DEFAULT FALSE, -- If TRUE, employee waives right to 96h notice (Ontario)

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- 2. AVAILABILITY
-- Raw data from Google Forms.
-- We store specific "Can Open" / "Can Close" booleans to match the simple Form input,
-- but strictly tie it to a date for accurate scheduling.
CREATE TABLE availability (
    id SERIAL PRIMARY KEY,
    employee_id UUID REFERENCES employees(id) ON DELETE CASCADE,
    shift_date DATE NOT NULL,

    -- PREFERENCES
    can_open BOOLEAN DEFAULT FALSE, -- e.g., Available 5:00 AM - 1:00 PM
    can_close BOOLEAN DEFAULT FALSE, -- e.g., Available 1:00 PM - 10:00 PM
    note TEXT, -- Specific constraints (e.g., "Must leave by 4pm")

    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(employee_id, shift_date) -- Prevent duplicate submissions for same day
);

-- 3. SHIFTS
-- The core schedule.
CREATE TABLE shifts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    employee_id UUID REFERENCES employees(id),

    -- TIMING
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,

    -- STATE MANAGEMENT
    status TEXT DEFAULT 'DRAFT', -- 'DRAFT', 'PUBLISHED', 'CONFIRMED', 'DECLINED'

    -- COMPLIANCE AUDIT
    -- If the AI/Manager schedules a "Clopen", we flag it here explicitly.
    is_clopen_violation BOOLEAN DEFAULT FALSE,
    violation_reason TEXT, -- e.g., "Rest period < 8 hours"
    manager_override_reason TEXT, -- Must be filled if violation exists

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. SHIFT_FEEDBACK (The AI "Gold Mine")
-- This table captures the human reaction to the schedule.
-- Future AI models will train on this to learn: "John always rejects closing shifts on Fridays."
CREATE TABLE shift_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shift_id UUID REFERENCES shifts(id),
    employee_id UUID REFERENCES employees(id),

    action TEXT NOT NULL, -- 'ACCEPTED', 'DECLINED', 'REQUEST_SWAP'
    reason_category TEXT, -- 'SICK', 'DISTANCE', 'BURNOUT', 'OTHER'
    reason_text TEXT, -- Raw text for NLP analysis

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- INDEXES for Performance
CREATE INDEX idx_shifts_employee_date ON shifts(employee_id, start_time);
CREATE INDEX idx_availability_date ON availability(shift_date);
