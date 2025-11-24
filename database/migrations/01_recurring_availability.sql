-- Migration: 01_recurring_availability.sql
-- Description: Create standard_availability table for recurring weekly availability
-- Date: 2025-11-23

-- Standard availability represents an employee's default weekly schedule
-- This is used when no specific availability record exists for a given date

CREATE TABLE IF NOT EXISTS standard_availability (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    day_of_week INT NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
    can_open BOOLEAN NOT NULL DEFAULT FALSE,
    can_close BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint: one record per employee per day of week
    CONSTRAINT unique_employee_day UNIQUE (employee_id, day_of_week)
);

-- Index for faster lookups by employee
CREATE INDEX IF NOT EXISTS idx_standard_availability_employee
ON standard_availability(employee_id);

-- Index for faster lookups by day of week
CREATE INDEX IF NOT EXISTS idx_standard_availability_day
ON standard_availability(day_of_week);

-- Comment on columns
COMMENT ON TABLE standard_availability IS 'Default weekly availability patterns for employees';
COMMENT ON COLUMN standard_availability.day_of_week IS '0=Monday, 1=Tuesday, ..., 6=Sunday';
COMMENT ON COLUMN standard_availability.can_open IS 'Can work OPEN shift (06:00-14:00)';
COMMENT ON COLUMN standard_availability.can_close IS 'Can work CLOSE shift (14:00-22:00). If both false, interpreted as MID-only';
