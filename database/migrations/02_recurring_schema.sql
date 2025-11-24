-- Migration: 02_recurring_schema.sql
-- Description: Update standard_availability day_of_week to use 0=Sunday convention
-- Date: 2025-11-23

-- Note: This migration updates the day_of_week convention to match standard calendar
-- 0=Sunday, 1=Monday, 2=Tuesday, 3=Wednesday, 4=Thursday, 5=Friday, 6=Saturday

-- Update existing records to new convention (shift Python weekday to calendar weekday)
-- Python: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
-- Calendar: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
-- Conversion: (python_day + 1) % 7

UPDATE standard_availability
SET day_of_week = (day_of_week + 1) % 7;

-- Update the comment
COMMENT ON COLUMN standard_availability.day_of_week IS '0=Sunday, 1=Monday, 2=Tuesday, 3=Wednesday, 4=Thursday, 5=Friday, 6=Saturday';
