-- database/seed.sql
-- 1. Insert 3 Employees (using real emails for testing)
INSERT INTO employees (full_name, email, role, max_weekly_hours) VALUES
('Sarah Barista', 'saprajayant@gmail.com', 'Barista', 40),
('John Closer', 'saprajayant03@gmail.com', 'Shift Lead', 44),
('Mike Opener', 'jayantsapra03@gmail.com', 'Barista', 20);

-- 2. Insert Availability for Next Week (assuming Monday start)
-- Sarah can work all day
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', TRUE, TRUE FROM employees WHERE email = 'saprajayant@gmail.com';

-- John can ONLY Close (He hates mornings)
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', FALSE, TRUE FROM employees WHERE email = 'saprajayant03@gmail.com';

-- Mike can ONLY Open
INSERT INTO availability (employee_id, shift_date, can_open, can_close)
SELECT id, CURRENT_DATE + INTERVAL '1 day', TRUE, FALSE FROM employees WHERE email = 'jayantsapra03@gmail.com';