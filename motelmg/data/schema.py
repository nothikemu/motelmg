"""Database schema, version 1.

Integrity is enforced in the database itself, not only in Python:

* foreign keys with RESTRICT / CASCADE semantics
* CHECK constraints for enumerations, amounts and date ordering
* partial UNIQUE indexes (e.g. one in-house reservation per room, one posted
  room charge per night, one open housekeeping task of a type per room)
* triggers that make it impossible to double-book a room even if a bug in the
  application logic tried to.
"""

SCHEMA_V1 = r"""
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------- staff ---
CREATE TABLE roles (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    is_system   INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    created_at  TEXT NOT NULL
);

CREATE TABLE role_permissions (
    role_id    INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    PRIMARY KEY (role_id, permission)
);

CREATE TABLE users (
    id                   INTEGER PRIMARY KEY,
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name            TEXT NOT NULL,
    email                TEXT NOT NULL DEFAULT '',
    phone                TEXT NOT NULL DEFAULT '',
    role_id              INTEGER NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
    password_hash        TEXT NOT NULL,
    is_active            INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)),
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    last_login_at        TEXT,
    password_changed_at  TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX idx_users_role ON users(role_id);

CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username    TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id   INTEGER,
    summary     TEXT NOT NULL,
    details     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_audit_ts ON audit_log(ts);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_user ON audit_log(user_id);
CREATE INDEX idx_audit_action ON audit_log(action);

-- ---------------------------------------------------------------- rooms ---
CREATE TABLE room_types (
    id            INTEGER PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description   TEXT NOT NULL DEFAULT '',
    beds          TEXT NOT NULL DEFAULT '',
    max_occupancy INTEGER NOT NULL DEFAULT 2 CHECK (max_occupancy BETWEEN 1 AND 20),
    base_rate     INTEGER NOT NULL CHECK (base_rate >= 0),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE rooms (
    id             INTEGER PRIMARY KEY,
    number         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    room_type_id   INTEGER NOT NULL REFERENCES room_types(id) ON DELETE RESTRICT,
    floor          TEXT NOT NULL DEFAULT '',
    beds           TEXT NOT NULL DEFAULT '',
    max_occupancy  INTEGER CHECK (max_occupancy IS NULL OR max_occupancy BETWEEN 1 AND 20),
    rate           INTEGER CHECK (rate IS NULL OR rate >= 0),
    description    TEXT NOT NULL DEFAULT '',
    features       TEXT NOT NULL DEFAULT '',
    hk_status      TEXT NOT NULL DEFAULT 'clean'
                   CHECK (hk_status IN ('dirty', 'cleaning', 'clean', 'inspected')),
    service_status TEXT NOT NULL DEFAULT 'in_service'
                   CHECK (service_status IN ('in_service', 'maintenance', 'out_of_service')),
    service_reason TEXT NOT NULL DEFAULT '',
    service_until  TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX idx_rooms_type ON rooms(room_type_id);

CREATE TABLE room_status_log (
    id        INTEGER PRIMARY KEY,
    room_id   INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    ts        TEXT NOT NULL,
    user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    field     TEXT NOT NULL CHECK (field IN ('hk_status', 'service_status')),
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL,
    reason    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_room_status_log_room ON room_status_log(room_id, ts);

-- --------------------------------------------------------------- guests ---
CREATE TABLE guests (
    id               INTEGER PRIMARY KEY,
    first_name       TEXT NOT NULL CHECK (length(trim(first_name)) > 0),
    last_name        TEXT NOT NULL CHECK (length(trim(last_name)) > 0),
    email            TEXT NOT NULL DEFAULT '',
    phone            TEXT NOT NULL DEFAULT '',
    phone_digits     TEXT NOT NULL DEFAULT '',
    address_line1    TEXT NOT NULL DEFAULT '',
    address_line2    TEXT NOT NULL DEFAULT '',
    city             TEXT NOT NULL DEFAULT '',
    state            TEXT NOT NULL DEFAULT '',
    postal_code      TEXT NOT NULL DEFAULT '',
    country          TEXT NOT NULL DEFAULT '',
    company          TEXT NOT NULL DEFAULT '',
    id_type          TEXT NOT NULL DEFAULT '',
    id_number        TEXT NOT NULL DEFAULT '',
    id_expiry        TEXT,
    date_of_birth    TEXT,
    vehicle_plate    TEXT NOT NULL DEFAULT '',
    preferences      TEXT NOT NULL DEFAULT '',
    is_vip           INTEGER NOT NULL DEFAULT 0 CHECK (is_vip IN (0, 1)),
    is_banned        INTEGER NOT NULL DEFAULT 0 CHECK (is_banned IN (0, 1)),
    banned_reason    TEXT NOT NULL DEFAULT '',
    created_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX idx_guests_name ON guests(last_name COLLATE NOCASE, first_name COLLATE NOCASE);
CREATE INDEX idx_guests_email ON guests(email COLLATE NOCASE);
CREATE INDEX idx_guests_phone ON guests(phone_digits);
CREATE UNIQUE INDEX ux_guests_document ON guests(id_type, id_number) WHERE id_number <> '';

-- --------------------------------------------------------- reservations ---
CREATE TABLE reservations (
    id                  INTEGER PRIMARY KEY,
    confirmation_no     TEXT NOT NULL UNIQUE,
    guest_id            INTEGER NOT NULL REFERENCES guests(id) ON DELETE RESTRICT,
    room_id             INTEGER NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
    room_type_id        INTEGER NOT NULL REFERENCES room_types(id) ON DELETE RESTRICT,
    check_in_date       TEXT NOT NULL,
    check_out_date      TEXT NOT NULL,
    adults              INTEGER NOT NULL DEFAULT 1 CHECK (adults BETWEEN 1 AND 20),
    children            INTEGER NOT NULL DEFAULT 0 CHECK (children BETWEEN 0 AND 20),
    status              TEXT NOT NULL DEFAULT 'confirmed'
                        CHECK (status IN ('confirmed', 'checked_in', 'checked_out', 'cancelled', 'no_show')),
    source              TEXT NOT NULL DEFAULT 'phone',
    is_walk_in          INTEGER NOT NULL DEFAULT 0 CHECK (is_walk_in IN (0, 1)),
    nightly_rate        INTEGER NOT NULL CHECK (nightly_rate >= 0),
    rate_overridden     INTEGER NOT NULL DEFAULT 0 CHECK (rate_overridden IN (0, 1)),
    discount_name       TEXT NOT NULL DEFAULT '',
    discount_bp         INTEGER NOT NULL DEFAULT 0 CHECK (discount_bp BETWEEN 0 AND 10000),
    expected_arrival    TEXT NOT NULL DEFAULT '',
    late_checkout_until TEXT NOT NULL DEFAULT '',
    special_requests    TEXT NOT NULL DEFAULT '',
    actual_check_in     TEXT,
    actual_check_out    TEXT,
    checked_in_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    checked_out_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    cancelled_at        TEXT,
    cancelled_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    cancel_reason       TEXT NOT NULL DEFAULT '',
    created_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    CHECK (check_out_date > check_in_date)
);
CREATE INDEX idx_res_dates ON reservations(check_in_date, check_out_date);
CREATE INDEX idx_res_out ON reservations(check_out_date);
CREATE INDEX idx_res_room ON reservations(room_id, status);
CREATE INDEX idx_res_guest ON reservations(guest_id);
CREATE INDEX idx_res_status ON reservations(status);
CREATE UNIQUE INDEX ux_res_one_in_house_per_room ON reservations(room_id) WHERE status = 'checked_in';

CREATE TRIGGER trg_res_no_double_booking_insert
BEFORE INSERT ON reservations
WHEN NEW.status IN ('confirmed', 'checked_in')
BEGIN
    SELECT RAISE(ABORT, 'ROOM_DOUBLE_BOOKED')
    WHERE EXISTS (
        SELECT 1 FROM reservations r
        WHERE r.room_id = NEW.room_id
          AND r.status IN ('confirmed', 'checked_in')
          AND r.check_in_date < NEW.check_out_date
          AND r.check_out_date > NEW.check_in_date
    );
END;

CREATE TRIGGER trg_res_no_double_booking_update
BEFORE UPDATE OF room_id, check_in_date, check_out_date, status ON reservations
WHEN NEW.status IN ('confirmed', 'checked_in')
BEGIN
    SELECT RAISE(ABORT, 'ROOM_DOUBLE_BOOKED')
    WHERE EXISTS (
        SELECT 1 FROM reservations r
        WHERE r.room_id = NEW.room_id
          AND r.id <> NEW.id
          AND r.status IN ('confirmed', 'checked_in')
          AND r.check_in_date < NEW.check_out_date
          AND r.check_out_date > NEW.check_in_date
    );
END;

CREATE TABLE room_moves (
    id             INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    from_room_id   INTEGER NOT NULL REFERENCES rooms(id),
    to_room_id     INTEGER NOT NULL REFERENCES rooms(id),
    moved_at       TEXT NOT NULL,
    moved_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reason         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_room_moves_res ON room_moves(reservation_id);

CREATE TABLE notes (
    id             INTEGER PRIMARY KEY,
    guest_id       INTEGER REFERENCES guests(id) ON DELETE CASCADE,
    reservation_id INTEGER REFERENCES reservations(id) ON DELETE CASCADE,
    room_id        INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
    body           TEXT NOT NULL CHECK (length(trim(body)) > 0),
    is_important   INTEGER NOT NULL DEFAULT 0 CHECK (is_important IN (0, 1)),
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL,
    CHECK ((guest_id IS NOT NULL) + (reservation_id IS NOT NULL) + (room_id IS NOT NULL) = 1)
);
CREATE INDEX idx_notes_guest ON notes(guest_id);
CREATE INDEX idx_notes_res ON notes(reservation_id);
CREATE INDEX idx_notes_room ON notes(room_id);

-- -------------------------------------------------------------- billing ---
CREATE TABLE taxes (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind       TEXT NOT NULL DEFAULT 'percent' CHECK (kind IN ('percent', 'fixed_per_night')),
    value      INTEGER NOT NULL CHECK (value >= 0),
    applies_to TEXT NOT NULL DEFAULT 'all' CHECK (applies_to IN ('room', 'extras', 'all')),
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE charge_items (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category       TEXT NOT NULL DEFAULT 'extra' CHECK (category IN ('fee', 'extra')),
    default_amount INTEGER NOT NULL DEFAULT 0 CHECK (default_amount >= 0),
    taxable        INTEGER NOT NULL DEFAULT 1 CHECK (taxable IN (0, 1)),
    auto_apply     TEXT NOT NULL DEFAULT 'none' CHECK (auto_apply IN ('none', 'per_night', 'per_stay')),
    system_code    TEXT UNIQUE,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    sort_order     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE discount_types (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    percent_bp INTEGER NOT NULL CHECK (percent_bp BETWEEN 1 AND 10000),
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE payment_methods (
    id                 INTEGER PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE COLLATE NOCASE,
    requires_reference INTEGER NOT NULL DEFAULT 0 CHECK (requires_reference IN (0, 1)),
    is_cash            INTEGER NOT NULL DEFAULT 0 CHECK (is_cash IN (0, 1)),
    is_active          INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    sort_order         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE charges (
    id             INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE RESTRICT,
    kind           TEXT NOT NULL CHECK (kind IN ('room', 'tax', 'fee', 'extra', 'discount', 'adjustment')),
    description    TEXT NOT NULL,
    service_date   TEXT NOT NULL,
    quantity       INTEGER NOT NULL DEFAULT 1 CHECK (quantity BETWEEN 1 AND 1000),
    unit_amount    INTEGER NOT NULL,
    amount         INTEGER NOT NULL,
    taxable        INTEGER NOT NULL DEFAULT 0 CHECK (taxable IN (0, 1)),
    parent_id      INTEGER REFERENCES charges(id) ON DELETE RESTRICT,
    tax_id         INTEGER REFERENCES taxes(id) ON DELETE RESTRICT,
    room_id        INTEGER REFERENCES rooms(id) ON DELETE RESTRICT,
    charge_item_id INTEGER REFERENCES charge_items(id) ON DELETE RESTRICT,
    is_void        INTEGER NOT NULL DEFAULT 0 CHECK (is_void IN (0, 1)),
    void_reason    TEXT NOT NULL DEFAULT '',
    voided_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    voided_at      TEXT,
    posted_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    posted_at      TEXT NOT NULL,
    CHECK (amount = quantity * unit_amount),
    CHECK (kind <> 'tax' OR tax_id IS NOT NULL)
);
CREATE INDEX idx_charges_res ON charges(reservation_id);
CREATE INDEX idx_charges_date ON charges(service_date);
CREATE INDEX idx_charges_parent ON charges(parent_id);
CREATE UNIQUE INDEX ux_charges_room_night ON charges(reservation_id, service_date)
    WHERE kind = 'room' AND is_void = 0;

CREATE TABLE payments (
    id             INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE RESTRICT,
    kind           TEXT NOT NULL CHECK (kind IN ('payment', 'deposit', 'refund')),
    method_id      INTEGER NOT NULL REFERENCES payment_methods(id) ON DELETE RESTRICT,
    amount         INTEGER NOT NULL CHECK (amount > 0),
    reference      TEXT NOT NULL DEFAULT '',
    notes          TEXT NOT NULL DEFAULT '',
    receipt_no     TEXT NOT NULL UNIQUE,
    is_void        INTEGER NOT NULL DEFAULT 0 CHECK (is_void IN (0, 1)),
    void_reason    TEXT NOT NULL DEFAULT '',
    voided_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    voided_at      TEXT,
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX idx_payments_res ON payments(reservation_id);
CREATE INDEX idx_payments_created ON payments(created_at);

CREATE TABLE invoices (
    id             INTEGER PRIMARY KEY,
    invoice_no     TEXT NOT NULL UNIQUE,
    reservation_id INTEGER NOT NULL UNIQUE REFERENCES reservations(id) ON DELETE RESTRICT,
    issued_at      TEXT NOT NULL,
    issued_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    total          INTEGER NOT NULL,
    paid           INTEGER NOT NULL,
    balance        INTEGER NOT NULL
);
CREATE INDEX idx_invoices_issued ON invoices(issued_at);

-- --------------------------------------------------------- housekeeping ---
CREATE TABLE housekeeping_tasks (
    id           INTEGER PRIMARY KEY,
    room_id      INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    task_type    TEXT NOT NULL
                 CHECK (task_type IN ('checkout', 'stayover', 'deep_clean', 'touch_up', 'inspection')),
    priority     INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 4),
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'in_progress', 'completed', 'inspected', 'cancelled')),
    assigned_to  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    notes        TEXT NOT NULL DEFAULT '',
    due_date     TEXT NOT NULL,
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    completed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    inspected_at TEXT,
    inspected_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    inspection_notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_hk_status ON housekeeping_tasks(status);
CREATE INDEX idx_hk_room ON housekeeping_tasks(room_id);
CREATE INDEX idx_hk_assigned ON housekeeping_tasks(assigned_to);
CREATE UNIQUE INDEX ux_hk_open_task ON housekeeping_tasks(room_id, task_type)
    WHERE status IN ('pending', 'in_progress');

-- ---------------------------------------------------------- maintenance ---
CREATE TABLE maintenance_tickets (
    id          INTEGER PRIMARY KEY,
    room_id     INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
    location    TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT 'other',
    priority    INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 4),
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'in_progress', 'on_hold', 'resolved', 'cancelled')),
    blocks_room INTEGER NOT NULL DEFAULT 0 CHECK (blocks_room IN (0, 1)),
    assigned_to TEXT NOT NULL DEFAULT '',
    reported_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    resolution  TEXT NOT NULL DEFAULT '',
    cost        INTEGER NOT NULL DEFAULT 0 CHECK (cost >= 0),
    CHECK (room_id IS NOT NULL OR length(trim(location)) > 0),
    CHECK (blocks_room = 0 OR room_id IS NOT NULL)
);
CREATE INDEX idx_mt_status ON maintenance_tickets(status);
CREATE INDEX idx_mt_room ON maintenance_tickets(room_id);

-- -------------------------------------------------------- notifications ---
CREATE TABLE notifications (
    id         INTEGER PRIMARY KEY,
    ts         TEXT NOT NULL,
    level      TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('info', 'warning', 'critical')),
    category   TEXT NOT NULL DEFAULT 'system',
    title      TEXT NOT NULL,
    message    TEXT NOT NULL DEFAULT '',
    is_read    INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1))
);

CREATE TABLE alert_dismissals (
    alert_key    TEXT NOT NULL,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dismissed_on TEXT NOT NULL,
    PRIMARY KEY (alert_key, user_id, dismissed_on)
);
"""
