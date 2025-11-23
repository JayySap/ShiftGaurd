-- database/seed.sql
-- 1. Insert 4 Employees (using real emails for testing)
INSERT INTO employees (full_name, email, role, max_weekly_hours) VALUES
('Sarah Barista', 'saprajayant@gmail.com', 'Barista', 40),         -- Flexible (True/True)
('John Closer', 'saprajayant03@gmail.com', 'Shift Lead', 44),      -- Close-Only
('Mike Opener', 'jayantsapra03@gmail.com', 'Barista', 20),         -- Open-Only
('Alex Mid', 'jsapra007@gmail.com', 'Barista', 32);                -- Mid-Only (False/False)

-- 2. Insert Availability for Next Week (assuming Monday start)
-- Sarah can work all shifts (Flexible: True/True)
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', TRUE, TRUE FROM employees WHERE email = 'saprajayant@gmail.com';

-- John can ONLY Close (Close-Only: False/True)
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', FALSE, TRUE FROM employees WHERE email = 'saprajayant03@gmail.com';

-- Mike can ONLY Open (Open-Only: True/False)
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', TRUE, FALSE FROM employees WHERE email = 'jayantsapra03@gmail.com';

-- Alex can ONLY work Mid shifts (Mid-Only: False/False)
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', FALSE, FALSE FROM employees WHERE email = 'jsapra007@gmail.com';
