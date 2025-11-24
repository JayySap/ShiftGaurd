-- CLEANUP
TRUNCATE TABLE shift_feedback CASCADE;
TRUNCATE TABLE shifts CASCADE;
TRUNCATE TABLE standard_availability CASCADE;
TRUNCATE TABLE employees CASCADE;

-- 1. INSERT 10 EMPLOYEES (Mix of Shift Leads & Baristas)
INSERT INTO employees (id, full_name, email, role, max_weekly_hours) VALUES
-- THE LEADERSHIP (Need one of these present at all times)
('11111111-1111-1111-1111-111111111111', 'Mike Manager', 'saprajayant@gmail.com', 'Shift Lead', 40),
('22222222-2222-2222-2222-222222222222', 'Sarah Supervisor', 'saprajayant03@gmail.com', 'Shift Lead', 40),
('33333333-3333-3333-3333-333333333333', 'Liam Lead', 'jayantsapra03@gmail.com', 'Shift Lead', 32),

-- THE FULL TIMERS (Open/Close Flexibility)
('44444444-4444-4444-4444-444444444444', 'Emma Earner', 'jsapra007@gmail.com', 'Barista', 40),
('55555555-5555-5555-5555-555555555555', 'John Job', 'jayant.sapra@sait.ca', 'Barista', 40),
('66666666-6666-6666-6666-666666666666', 'Olivia Open', 'olivia@test.com', 'Barista', 35),

-- THE PART TIMERS / STUDENTS (Restricted Availability)
('77777777-7777-7777-7777-777777777777', 'Alex Afternoon', 'alex@test.com', 'Barista', 20),
('88888888-8888-8888-8888-888888888888', 'Noah Night', 'noah@test.com', 'Barista', 20),
('99999999-9999-9999-9999-999999999999', 'Lucas Late', 'lucas@test.com', 'Barista', 15),
('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Sophia Student', 'sophia@test.com', 'Barista', 12);

-- 2. INSERT STANDARD AVAILABILITY (Recurring Rules)

-- MIKE (Lead): Opens Mon-Fri
INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close) VALUES
('11111111-1111-1111-1111-111111111111', 1, TRUE, FALSE), -- Mon
('11111111-1111-1111-1111-111111111111', 2, TRUE, FALSE), -- Tue
('11111111-1111-1111-1111-111111111111', 3, TRUE, FALSE), -- Wed
('11111111-1111-1111-1111-111111111111', 4, TRUE, FALSE), -- Thu
('11111111-1111-1111-1111-111111111111', 5, TRUE, FALSE); -- Fri

-- SARAH (Lead): Closes Mon-Fri
INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close) VALUES
('22222222-2222-2222-2222-222222222222', 1, FALSE, TRUE),
('22222222-2222-2222-2222-222222222222', 2, FALSE, TRUE),
('22222222-2222-2222-2222-222222222222', 3, FALSE, TRUE),
('22222222-2222-2222-2222-222222222222', 4, FALSE, TRUE),
('22222222-2222-2222-2222-222222222222', 5, FALSE, TRUE);

-- LIAM (Lead): Weekends All Day + Wed Mid
INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close) VALUES
('33333333-3333-3333-3333-333333333333', 6, TRUE, TRUE), -- Sat
('33333333-3333-3333-3333-333333333333', 0, TRUE, TRUE), -- Sun
('33333333-3333-3333-3333-333333333333', 3, TRUE, TRUE); -- Wed

-- EMMA & JOHN (Full Flex): Available Every Day
INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close)
SELECT '44444444-4444-4444-4444-444444444444', generate_series(0,6), TRUE, TRUE; -- Emma

INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close)
SELECT '55555555-5555-5555-5555-555555555555', generate_series(0,6), TRUE, TRUE; -- John

-- OLIVIA: Mornings Only (Mon-Sat)
INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close)
SELECT '66666666-6666-6666-6666-666666666666', generate_series(1,6), TRUE, FALSE;

-- ALEX: Mids Only (Mon-Fri) - (False/False implies Mid)
INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close)
SELECT '77777777-7777-7777-7777-777777777777', generate_series(1,5), FALSE, FALSE;

-- NOAH: Nights Only (Thu-Sun)
INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close) VALUES
('88888888-8888-8888-8888-888888888888', 4, FALSE, TRUE),
('88888888-8888-8888-8888-888888888888', 5, FALSE, TRUE),
('88888888-8888-8888-8888-888888888888', 6, FALSE, TRUE),
('88888888-8888-8888-8888-888888888888', 0, FALSE, TRUE);

-- SOPHIA & LUCAS: Weekends Only
INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close) VALUES
('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 6, TRUE, TRUE), -- Sophia Sat
('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 0, TRUE, TRUE), -- Sophia Sun
('99999999-9999-9999-9999-999999999999', 6, FALSE, TRUE), -- Lucas Sat
('99999999-9999-9999-9999-999999999999', 0, FALSE, TRUE); -- Lucas Sun