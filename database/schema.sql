-- ============================================================================
-- Face Recognition Attendance System - Database Schema
-- PostgreSQL 14+
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Students Table
CREATE TABLE students (
    student_id VARCHAR(20) PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20),
    enrollment_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'graduated', 'withdrawn')),
    face_encoding BYTEA, -- Binary storage for 128-d embedding (512 bytes)
    face_encoding_version VARCHAR(10) DEFAULT 'v1.0', -- For model versioning
    last_encoding_update TIMESTAMP WITH TIME ZONE,
    profile_photo_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_students_status ON students(status);
CREATE INDEX idx_students_email ON students(email);

-- Classrooms Table
CREATE TABLE classrooms (
    classroom_id VARCHAR(20) PRIMARY KEY,
    building VARCHAR(50) NOT NULL,
    room_number VARCHAR(20) NOT NULL,
    capacity INT NOT NULL CHECK (capacity > 0),
    floor INT,
    room_type VARCHAR(30) CHECK (room_type IN ('lecture_hall', 'lab', 'seminar_room', 'auditorium')),
    raspberry_pi_uuid UUID UNIQUE, -- Links to edge device
    raspberry_pi_mac_address VARCHAR(17),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(building, room_number)
);

CREATE INDEX idx_classrooms_pi_uuid ON classrooms(raspberry_pi_uuid);
CREATE INDEX idx_classrooms_active ON classrooms(is_active);

-- Courses Table
CREATE TABLE courses (
    course_id VARCHAR(20) PRIMARY KEY,
    course_code VARCHAR(10) UNIQUE NOT NULL,
    course_name VARCHAR(200) NOT NULL,
    department VARCHAR(100) NOT NULL,
    credits INT CHECK (credits > 0),
    semester VARCHAR(20), -- e.g., "Fall 2024", "Spring 2025"
    academic_year VARCHAR(10), -- e.g., "2024-25"
    instructor_id VARCHAR(20), -- FK to faculty table (not implemented here)
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_courses_code ON courses(course_code);
CREATE INDEX idx_courses_semester ON courses(semester);
CREATE INDEX idx_courses_active ON courses(is_active);

-- Enrollments Table (Many-to-Many: Students ↔ Courses)
CREATE TABLE enrollments (
    enrollment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_id VARCHAR(20) NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    course_id VARCHAR(20) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    enrollment_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status VARCHAR(20) DEFAULT 'enrolled' CHECK (status IN ('enrolled', 'dropped', 'completed', 'failed')),
    grade VARCHAR(5), -- e.g., "A+", "B", "C"
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, course_id)
);

CREATE INDEX idx_enrollments_student ON enrollments(student_id);
CREATE INDEX idx_enrollments_course ON enrollments(course_id);
CREATE INDEX idx_enrollments_status ON enrollments(status);

-- Schedules Table (When and where courses meet)
CREATE TABLE schedules (
    schedule_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id VARCHAR(20) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    classroom_id VARCHAR(20) NOT NULL REFERENCES classrooms(classroom_id) ON DELETE CASCADE,
    day_of_week INT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6), -- 0=Monday, 6=Sunday
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    effective_from DATE NOT NULL, -- Schedule validity period
    effective_to DATE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    recurrence_rule TEXT, -- Optional: iCal RRULE for complex patterns
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CHECK (end_time > start_time),
    CHECK (effective_to >= effective_from)
);

CREATE INDEX idx_schedules_course ON schedules(course_id);
CREATE INDEX idx_schedules_classroom ON schedules(classroom_id);
CREATE INDEX idx_schedules_day_time ON schedules(day_of_week, start_time);
CREATE INDEX idx_schedules_effective ON schedules(effective_from, effective_to);

-- Attendance Logs Table (Partitioned by date for performance)
CREATE TABLE attendance_logs (
    log_id UUID DEFAULT uuid_generate_v4(),
    student_id VARCHAR(20) NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    course_id VARCHAR(20) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    schedule_id UUID REFERENCES schedules(schedule_id) ON DELETE SET NULL,
    classroom_id VARCHAR(20) NOT NULL REFERENCES classrooms(classroom_id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date DATE NOT NULL GENERATED ALWAYS AS (DATE(timestamp)) STORED,
    confidence_score NUMERIC(4, 3) CHECK (confidence_score >= 0 AND confidence_score <= 1),
    device_id UUID NOT NULL, -- Raspberry Pi UUID
    device_ip INET,
    status VARCHAR(20) DEFAULT 'present' CHECK (status IN ('present', 'late', 'left_early', 'manual_override')),
    is_verified BOOLEAN DEFAULT FALSE, -- Manual verification by faculty
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (log_id, date)
) PARTITION BY RANGE (date);

-- Create partitions for current and next 12 months
CREATE TABLE attendance_logs_2024_01 PARTITION OF attendance_logs
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE attendance_logs_2024_02 PARTITION OF attendance_logs
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
-- ... (Add partitions programmatically in production)

CREATE INDEX idx_attendance_student_date ON attendance_logs(student_id, date);
CREATE INDEX idx_attendance_course_date ON attendance_logs(course_id, date);
CREATE INDEX idx_attendance_device ON attendance_logs(device_id);
CREATE INDEX idx_attendance_timestamp ON attendance_logs(timestamp);

-- ============================================================================
-- OPERATIONAL TABLES
-- ============================================================================

-- Edge Devices Registry (Raspberry Pi fleet management)
CREATE TABLE edge_devices (
    device_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_name VARCHAR(100) UNIQUE NOT NULL,
    mac_address VARCHAR(17) UNIQUE,
    ip_address INET,
    classroom_id VARCHAR(20) REFERENCES classrooms(classroom_id) ON DELETE SET NULL,
    model VARCHAR(50), -- e.g., "Raspberry Pi 5 8GB"
    os_version VARCHAR(50),
    app_version VARCHAR(20),
    last_heartbeat TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'online' CHECK (status IN ('online', 'offline', 'maintenance', 'error')),
    cpu_temp_celsius NUMERIC(4, 1),
    disk_usage_percent NUMERIC(5, 2),
    cache_size_mb INT,
    total_faces_processed BIGINT DEFAULT 0,
    api_key_hash TEXT, -- bcrypt hash for authentication
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_devices_status ON edge_devices(status);
CREATE INDEX idx_devices_classroom ON edge_devices(classroom_id);
CREATE INDEX idx_devices_heartbeat ON edge_devices(last_heartbeat);

-- API Audit Log (Security and debugging)
CREATE TABLE api_audit_log (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_uuid UUID REFERENCES edge_devices(device_uuid) ON DELETE SET NULL,
    endpoint VARCHAR(255) NOT NULL,
    http_method VARCHAR(10) NOT NULL,
    status_code INT NOT NULL,
    request_payload JSONB,
    response_time_ms INT,
    ip_address INET,
    user_agent TEXT,
    error_message TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
) PARTITION BY RANGE (timestamp);

-- Create partitions (monthly)
CREATE TABLE api_audit_log_2024_01 PARTITION OF api_audit_log
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE INDEX idx_audit_device ON api_audit_log(device_uuid);
CREATE INDEX idx_audit_endpoint ON api_audit_log(endpoint);
CREATE INDEX idx_audit_timestamp ON api_audit_log(timestamp);

-- Sync Queue (For Pi → Cloud data sync failures)
CREATE TABLE sync_queue (
    queue_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_uuid UUID NOT NULL REFERENCES edge_devices(device_uuid) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 5,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_sync_queue_status ON sync_queue(status);
CREATE INDEX idx_sync_queue_device ON sync_queue(device_uuid);

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Current Schedule View (What's happening now in each classroom)
CREATE OR REPLACE VIEW current_schedule AS
SELECT
    s.schedule_id,
    s.course_id,
    c.course_code,
    c.course_name,
    s.classroom_id,
    cr.building,
    cr.room_number,
    s.start_time,
    s.end_time,
    s.day_of_week,
    cr.raspberry_pi_uuid
FROM schedules s
JOIN courses c ON s.course_id = c.course_id
JOIN classrooms cr ON s.classroom_id = cr.classroom_id
WHERE s.is_active = TRUE
  AND c.is_active = TRUE
  AND cr.is_active = TRUE
  AND CURRENT_DATE BETWEEN s.effective_from AND s.effective_to;

-- Student Attendance Summary (Per course)
CREATE OR REPLACE VIEW student_attendance_summary AS
SELECT
    e.student_id,
    s.first_name,
    s.last_name,
    e.course_id,
    c.course_code,
    c.course_name,
    COUNT(DISTINCT al.date) AS classes_attended,
    COUNT(DISTINCT sch.schedule_id) AS total_classes,
    ROUND(
        (COUNT(DISTINCT al.date)::NUMERIC / NULLIF(COUNT(DISTINCT sch.schedule_id), 0)) * 100,
        2
    ) AS attendance_percentage
FROM enrollments e
JOIN students s ON e.student_id = s.student_id
JOIN courses c ON e.course_id = c.course_id
LEFT JOIN schedules sch ON sch.course_id = c.course_id
    AND sch.effective_from <= CURRENT_DATE
    AND sch.effective_to >= CURRENT_DATE
LEFT JOIN attendance_logs al ON al.student_id = s.student_id
    AND al.course_id = c.course_id
WHERE e.status = 'enrolled'
GROUP BY e.student_id, s.first_name, s.last_name, e.course_id, c.course_code, c.course_name;

-- ============================================================================
-- FUNCTIONS AND TRIGGERS
-- ============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to relevant tables
CREATE TRIGGER update_students_updated_at BEFORE UPDATE ON students
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_classrooms_updated_at BEFORE UPDATE ON classrooms
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_courses_updated_at BEFORE UPDATE ON courses
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_enrollments_updated_at BEFORE UPDATE ON enrollments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_schedules_updated_at BEFORE UPDATE ON schedules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_edge_devices_updated_at BEFORE UPDATE ON edge_devices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to get enrolled students for a given classroom and time
CREATE OR REPLACE FUNCTION get_enrolled_students_for_class(
    p_classroom_id VARCHAR(20),
    p_check_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
)
RETURNS TABLE (
    student_id VARCHAR(20),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    email VARCHAR(255),
    face_encoding BYTEA,
    course_id VARCHAR(20),
    course_name VARCHAR(200)
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        s.student_id,
        s.first_name,
        s.last_name,
        s.email,
        s.face_encoding,
        c.course_id,
        c.course_name
    FROM students s
    JOIN enrollments e ON s.student_id = e.student_id
    JOIN courses c ON e.course_id = c.course_id
    JOIN schedules sch ON c.course_id = sch.course_id
    WHERE sch.classroom_id = p_classroom_id
      AND e.status = 'enrolled'
      AND s.status = 'active'
      AND c.is_active = TRUE
      AND sch.is_active = TRUE
      AND s.face_encoding IS NOT NULL
      AND EXTRACT(DOW FROM p_check_time) = sch.day_of_week
      AND p_check_time::TIME BETWEEN sch.start_time AND sch.end_time
      AND p_check_time::DATE BETWEEN sch.effective_from AND sch.effective_to;
END;
$$ LANGUAGE plpgsql;

-- Function to prevent duplicate attendance (within 30 seconds)
CREATE OR REPLACE FUNCTION check_duplicate_attendance()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM attendance_logs
        WHERE student_id = NEW.student_id
          AND course_id = NEW.course_id
          AND date = NEW.date
          AND timestamp > NEW.timestamp - INTERVAL '30 seconds'
          AND timestamp < NEW.timestamp + INTERVAL '30 seconds'
    ) THEN
        RAISE EXCEPTION 'Duplicate attendance detected for student % in course % within 30 seconds',
            NEW.student_id, NEW.course_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_duplicate_attendance BEFORE INSERT ON attendance_logs
    FOR EACH ROW EXECUTE FUNCTION check_duplicate_attendance();

-- ============================================================================
-- SAMPLE DATA (For testing)
-- ============================================================================

-- Insert sample students
INSERT INTO students (student_id, first_name, last_name, email, phone, face_encoding_version) VALUES
('S001', 'Alice', 'Johnson', 'alice.j@university.edu', '555-0101', 'v1.0'),
('S002', 'Bob', 'Smith', 'bob.s@university.edu', '555-0102', 'v1.0'),
('S003', 'Charlie', 'Brown', 'charlie.b@university.edu', '555-0103', 'v1.0'),
('S004', 'Diana', 'Prince', 'diana.p@university.edu', '555-0104', 'v1.0'),
('S005', 'Eve', 'Williams', 'eve.w@university.edu', '555-0105', 'v1.0');

-- Insert sample classrooms
INSERT INTO classrooms (classroom_id, building, room_number, capacity, floor, room_type, raspberry_pi_uuid) VALUES
('LAB-301', 'Engineering Block', '301', 60, 3, 'lab', 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'),
('LH-101', 'Main Building', '101', 120, 1, 'lecture_hall', 'b1ffcd99-8c1b-5ef9-cc7e-7cc9cd491b22'),
('SEM-205', 'Liberal Arts', '205', 30, 2, 'seminar_room', 'c2ggde99-7c2c-6efa-dd8f-8dd9de5a2c33');

-- Insert sample courses
INSERT INTO courses (course_id, course_code, course_name, department, credits, semester, academic_year) VALUES
('CS101', 'CSE101', 'Data Structures', 'Computer Science', 4, 'Fall 2024', '2024-25'),
('CS102', 'CSE102', 'Algorithms', 'Computer Science', 4, 'Fall 2024', '2024-25'),
('MATH201', 'MATH201', 'Linear Algebra', 'Mathematics', 3, 'Fall 2024', '2024-25');

-- Insert sample enrollments
INSERT INTO enrollments (student_id, course_id, status) VALUES
('S001', 'CS101', 'enrolled'),
('S002', 'CS101', 'enrolled'),
('S003', 'CS101', 'enrolled'),
('S001', 'CS102', 'enrolled'),
('S004', 'MATH201', 'enrolled'),
('S005', 'MATH201', 'enrolled');

-- Insert sample schedules (Monday = 0, Tuesday = 1, etc.)
INSERT INTO schedules (course_id, classroom_id, day_of_week, start_time, end_time, effective_from, effective_to) VALUES
('CS101', 'LAB-301', 1, '09:00', '10:30', '2024-01-01', '2024-05-31'), -- Tuesday
('CS101', 'LAB-301', 4, '09:00', '10:30', '2024-01-01', '2024-05-31'), -- Friday
('CS102', 'LH-101', 2, '14:00', '15:30', '2024-01-01', '2024-05-31'), -- Wednesday
('MATH201', 'SEM-205', 0, '11:00', '12:30', '2024-01-01', '2024-05-31'); -- Monday

-- Insert sample edge device
INSERT INTO edge_devices (device_uuid, device_name, mac_address, classroom_id, model, app_version, status) VALUES
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'PI-LAB301', 'DC:A6:32:12:34:56', 'LAB-301', 'Raspberry Pi 5 8GB', 'v1.0.0', 'online');

-- ============================================================================
-- INDEXES FOR PERFORMANCE OPTIMIZATION
-- ============================================================================

-- Composite index for schedule lookup (hot path)
CREATE INDEX idx_schedules_lookup ON schedules(classroom_id, day_of_week, start_time, end_time)
    WHERE is_active = TRUE;

-- Index for attendance aggregation queries
CREATE INDEX idx_attendance_aggregation ON attendance_logs(course_id, student_id, date);

-- ============================================================================
-- DATABASE MAINTENANCE
-- ============================================================================

-- Automatically create new partitions (run monthly via cron/scheduled job)
CREATE OR REPLACE FUNCTION create_monthly_partitions()
RETURNS VOID AS $$
DECLARE
    partition_date DATE;
    partition_name TEXT;
    start_date TEXT;
    end_date TEXT;
BEGIN
    FOR i IN 0..2 LOOP  -- Create next 3 months
        partition_date := DATE_TRUNC('month', CURRENT_DATE + (i || ' months')::INTERVAL);
        partition_name := 'attendance_logs_' || TO_CHAR(partition_date, 'YYYY_MM');
        start_date := TO_CHAR(partition_date, 'YYYY-MM-DD');
        end_date := TO_CHAR(partition_date + INTERVAL '1 month', 'YYYY-MM-DD');

        EXECUTE FORMAT(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF attendance_logs FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_date, end_date
        );
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================================================

COMMENT ON TABLE students IS 'Core student information with face embeddings';
COMMENT ON COLUMN students.face_encoding IS '128-dimensional face embedding stored as binary (512 bytes)';
COMMENT ON TABLE attendance_logs IS 'Partitioned table storing all attendance events';
COMMENT ON FUNCTION get_enrolled_students_for_class IS 'Returns students enrolled in the class scheduled for given classroom and time';
