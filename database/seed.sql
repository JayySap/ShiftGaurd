-- database/seed.sql
-- 1. Insert 3 Employees
INSERT INTO employees (full_name, email, role, max_weekly_hours) VALUES
('Sarah Barista', 'sarah@example.com', 'Barista', 40),
('John Closer', 'john@example.com', 'Shift Lead', 44),
('Mike Opener', 'mike@example.com', 'Barista', 20);

-- 2. Insert Availability for Next Week (assuming Monday start)
-- Sarah can work all day
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', TRUE, TRUE FROM employees WHERE email = 'sarah@example.com';

-- John can ONLY Close (He hates mornings)
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', FALSE, TRUE FROM employees WHERE email = 'john@example.com';

-- Mike can ONLY Open
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', TRUE, FALSE FROM employees WHERE email = 'mike@example.com';