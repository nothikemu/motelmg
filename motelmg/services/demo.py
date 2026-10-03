"""Optional demo data so a new user can explore a realistic, populated system.

The generator *replays* several weeks of front desk activity through the real
services (bookings, check-ins, payments, check-outs, housekeeping, maintenance)
by moving the application clock day by day, so every record it creates is
exactly what the application would have produced in normal use.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, time, timedelta

from motelmg.core.errors import MotelError

log = logging.getLogger(__name__)

FIRST = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth",
         "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Carlos", "Karen",
         "Daniel", "Lisa", "Matthew", "Nancy", "Anthony", "Sandra", "Mark", "Ashley", "Steven", "Emily", "Kevin",
         "Michelle", "Brian", "Amanda", "Priya", "Wei", "Fatima", "Diego", "Aisha", "Hiroshi"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
        "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Patel"]
CITIES = [("Denver", "CO"), ("Austin", "TX"), ("Phoenix", "AZ"), ("Omaha", "NE"), ("Boise", "ID"), ("Tulsa", "OK"),
          ("Reno", "NV"), ("Fresno", "CA"), ("Wichita", "KS"), ("Spokane", "WA"), ("Des Moines", "IA"),
          ("Salt Lake City", "UT"), ("Albuquerque", "NM"), ("Kansas City", "MO"), ("Billings", "MT")]
ISSUES = [("Leaking faucet in bathroom", "plumbing"), ("AC not cooling", "hvac"), ("TV remote missing", "electronics"),
          ("Wi-Fi drops frequently", "electronics"), ("Door lock battery low", "locks"),
          ("Shower drain clogged", "plumbing"), ("Light fixture flickering", "electrical"),
          ("Mini fridge not cold", "appliance"), ("Broken drawer handle", "furniture"),
          ("Window does not latch", "structural")]
REQUESTS = ["Ground floor please", "Late arrival around 10 PM", "Extra pillows", "Quiet room away from ice machine",
            "Traveling with a small dog", "Needs parking for a trailer", "", "", "", ""]


def generate_demo_data(ctx, days_back: int = 42, days_ahead: int = 21, seed: int = 7) -> None:
    rng = random.Random(seed)
    real_now = ctx.clock.now()
    admin_session = ctx.session
    try:
        _run(ctx, rng, real_now, days_back, days_ahead)
    finally:
        ctx.clock.set(None)
        ctx.session = admin_session
    ctx.events.emit("*")


def _run(ctx, rng: random.Random, real_now: datetime, days_back: int, days_ahead: int) -> None:
    today = real_now.date()
    start = today - timedelta(days=days_back)
    ctx.clock.set(datetime.combine(start - timedelta(days=1), time(9)))

    roles = {r.name: r.id for r in ctx.users.list_roles()}
    staff = {}
    for username, name, role in (("maria", "Maria Lopez", "Housekeeping"), ("ana", "Ana Silva", "Housekeeping"),
                                 ("james", "James Carter", "Front Desk"), ("sam", "Sam Okafor", "Maintenance"),
                                 ("linda", "Linda Park", "Manager")):
        if not ctx.repo_staff.get_user_row(username):
            staff[username] = ctx.users.create_user({"full_name": name, "username": username, "role_id": roles[role]},
                                                    "Welcome123", must_change=True)
        else:
            staff[username] = ctx.repo_staff.get_user_row(username)["id"]

    ctx.catalog.save_charge_item(None, {"name": "Breakfast voucher", "category": "extra", "default_amount": "9.50",
                                        "taxable": True})
    methods = [m.id for m in ctx.catalog.payment_methods()]
    card = next(m.id for m in ctx.catalog.payment_methods() if m.name == "Credit card")
    cash = next(m.id for m in ctx.catalog.payment_methods() if m.is_cash)
    items = [i for i in ctx.catalog.charge_items() if not i.system_code and i.default_amount]
    discounts = [d.id for d in ctx.catalog.discount_types()]

    guests: list[int] = []
    for i in range(70):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        city, state = rng.choice(CITIES)
        try:
            guests.append(ctx.guests.create({
                "first_name": first, "last_name": last,
                "email": f"{first.lower()}.{last.lower()}{i}@example.com",
                "phone": f"({rng.randint(201, 989)}) 555-{rng.randint(1000, 9999)}",
                "address_line1": f"{rng.randint(10, 9999)} {rng.choice(['Oak', 'Maple', 'Main', 'Cedar', 'Pine'])} "
                                 f"{rng.choice(['St', 'Ave', 'Rd', 'Blvd'])}",
                "city": city, "state": state, "postal_code": f"{rng.randint(10000, 99999)}", "country": "USA",
                "id_type": "drivers_license", "id_number": f"{state}{rng.randint(1000000, 9999999)}",
                "vehicle_plate": f"{rng.choice('ABCDEFGHJK')}{rng.choice('LMNPRSTUVW')}{rng.randint(1000, 9999)}",
                "is_vip": rng.random() < 0.08,
            }))
        except MotelError:
            continue
    rooms = ctx.rooms.list_rooms()

    def book(arrival, nights, guest_id=None, source=None):
        guest_id = guest_id or rng.choice(guests)
        departure = arrival + timedelta(days=nights)
        free = ctx.rooms.available_rooms(arrival, departure)
        if not free:
            return None
        room = rng.choice(free)
        data = {"guest_id": guest_id, "room_id": room.id, "check_in_date": arrival, "check_out_date": departure,
                "adults": rng.randint(1, min(2, room.capacity)), "children": 0,
                "source": source or rng.choice(["phone", "phone", "website", "website", "ota", "email", "corporate"]),
                "special_requests": rng.choice(REQUESTS),
                "expected_arrival": rng.choice(["", "15:00", "16:30", "18:00", "20:00"])}
        if discounts and rng.random() < 0.15:
            data["discount_id"] = rng.choice(discounts)
        try:
            res_id = ctx.reservations.create(data)
        except MotelError:
            return None
        if rng.random() < 0.35:
            try:
                ctx.billing.record_payment(res_id, amount=f"{room.effective_rate / 100:.2f}", method_id=card,
                                           reference=str(rng.randint(1000, 9999)))
            except MotelError:
                pass
        return res_id

    def phase(day, hour: int, minute: int = 0) -> bool:
        """Move the clock to ``day hour:minute`` unless that is still in the future."""
        moment = datetime.combine(day, time(hour, minute))
        if moment > real_now:
            return False
        ctx.clock.set(moment)
        return True

    open_tickets: list[tuple[int, int]] = []
    for offset in range(days_back + 1):
        day = start + timedelta(days=offset)
        is_today = day == today

        # Morning: departures settle and leave.
        departing = [r for r in (ctx.repo_res.in_house() if phase(day, 9, rng.randint(0, 50)) else [])
                     if r.check_out_date <= day]
        if is_today and departing:
            departing = departing[1:]  # leave a departure for the user to process
        for res in departing:
            ctx.clock.advance(minutes=rng.randint(3, 15))
            balance = ctx.billing.balance(res.id)
            payment = {"amount": f"{balance / 100:.2f}", "method_id": rng.choice([card, card, cash] + methods[:1]),
                       "reference": str(rng.randint(1000, 9999))} if balance > 0 else None
            allow_balance = rng.random() < 0.05
            if allow_balance:
                payment = None
            try:
                ctx.reservations.check_out(res.id, payment=payment, allow_balance=allow_balance)
            except MotelError as exc:
                log.debug("demo checkout skipped: %s", exc)

        # Housekeeping cleans dirty rooms around midday.
        for task in (ctx.repo_hk.search(day, statuses=["pending"]) if phase(day, 11) else []):
            if is_today and rng.random() < 0.6:
                continue
            maid = rng.choice([staff["maria"], staff["ana"]])
            try:
                ctx.housekeeping.assign([task.id], maid)
                ctx.clock.advance(minutes=rng.randint(5, 20))
                ctx.housekeeping.start(task.id)
                ctx.clock.advance(minutes=rng.randint(18, 45))
                ctx.housekeeping.complete(task.id)
                if rng.random() < 0.6:
                    ctx.housekeeping.inspect(task.id, True)
            except MotelError as exc:
                log.debug("demo housekeeping skipped: %s", exc)

        # Maintenance: open and resolve tickets.
        if not phase(day, 13, rng.randint(0, 59)):
            continue
        for ticket_id, due in list(open_tickets):
            if due <= offset and not (is_today and rng.random() < 0.5):
                try:
                    ctx.maintenance.resolve(ticket_id, rng.choice(["Repaired", "Replaced part", "Vendor fixed issue"]),
                                            f"{rng.randint(0, 180)}.00")
                except MotelError:
                    pass
                open_tickets.remove((ticket_id, due))
        if rng.random() < 0.3:
            title, category = rng.choice(ISSUES)
            room = rng.choice(rooms)
            vacant = not ctx.repo_res.in_house_for_room(room.id)
            try:
                ticket_id, _ = ctx.maintenance.create({
                    "room_id": room.id, "title": title, "category": category,
                    "priority": rng.choice([2, 3, 3, 4]), "blocks_room": vacant and rng.random() < 0.35,
                    "assigned_to": rng.choice(["Sam", "ABC Plumbing", "CoolAir HVAC", ""])})
                open_tickets.append((ticket_id, offset + rng.randint(0, 3)))
            except MotelError:
                pass

        # Afternoon: arrivals check in (a few no-shows).
        if phase(day, 15, rng.randint(0, 40)):
            for res in ctx.repo_res.stale_confirmed(day):
                try:
                    ctx.reservations.mark_no_show(res.id, fee=f"{res.nightly_rate / 100:.2f}"
                                                  if rng.random() < 0.5 else None)
                except MotelError:
                    pass
        for res in (ctx.repo_res.arrivals_pending(day) if phase(day, 15, rng.randint(0, 40)) else []):
            if is_today and rng.random() < 0.55:
                continue
            ctx.clock.advance(minutes=rng.randint(5, 25))
            if res.check_in_date < day:
                try:
                    ctx.reservations.mark_no_show(res.id, fee=f"{res.nightly_rate / 100:.2f}"
                                                  if rng.random() < 0.5 else None)
                except MotelError:
                    pass
                continue
            if rng.random() < 0.04 and not is_today:
                continue  # becomes a no-show tomorrow
            try:
                ctx.reservations.check_in(res.id, allow_dirty=True)
                if rng.random() < 0.7:
                    est = ctx.billing.balance(res.id)
                    if est > 0:
                        ctx.billing.record_payment(res.id, amount=f"{est / 100:.2f}", method_id=card,
                                                   reference=str(rng.randint(1000, 9999)))
            except MotelError as exc:
                log.debug("demo check-in skipped: %s", exc)

        # Evening: extras, walk-ins, new bookings and cancellations.
        if not phase(day, 19, rng.randint(0, 59)):
            continue
        for res in ctx.repo_res.in_house():
            if items and rng.random() < 0.18:
                item = rng.choice(items)
                try:
                    ctx.billing.post_charge(res.id, {"item_id": item.id, "amount": f"{item.default_amount / 100:.2f}",
                                                     "quantity": rng.randint(1, 2)})
                except MotelError:
                    pass
        if rng.random() < 0.5:
            free = ctx.rooms.available_rooms(day, day + timedelta(days=1))
            free = [r for r in free if r.hk_status in ("clean", "inspected")]
            if free:
                try:
                    ctx.reservations.walk_in({"guest_id": rng.choice(guests), "room_id": rng.choice(free).id,
                                              "nights": rng.randint(1, 2), "adults": 1},
                                             payment={"amount": f"{free[0].effective_rate / 100:.2f}",
                                                      "method_id": cash})
                except MotelError as exc:
                    log.debug("demo walk-in skipped: %s", exc)
        for _ in range(rng.randint(2, 5)):
            lead = rng.choice([0, 1, 1, 2, 3, 5, 7, 10, 14, 20])
            book(day + timedelta(days=lead), rng.choice([1, 1, 1, 2, 2, 3, 4, 7]))
        future = ctx.repo_res.search(statuses=["confirmed"], arrival_from=day + timedelta(days=1))
        if future and rng.random() < 0.25:
            victim = rng.choice(future)
            try:
                ctx.reservations.cancel(victim.id, rng.choice(["Change of plans", "Found another hotel",
                                                               "Trip cancelled", "Booked by mistake"]))
                if ctx.billing.balance(victim.id) < 0:
                    ctx.billing.refund(victim.id, amount=f"{-ctx.billing.balance(victim.id) / 100:.2f}",
                                       method_id=card, reason="Deposit refunded on cancellation")
            except MotelError:
                pass

    # Future bookings so the calendar looks realistic.
    ctx.clock.set(real_now)
    for _ in range(days_ahead):
        book(today + timedelta(days=rng.randint(1, days_ahead)), rng.choice([1, 2, 2, 3, 5]))
    # Make sure today has a few pending arrivals for the user to check in.
    for _ in range(2):
        book(today, rng.choice([1, 2, 3]))
    ctx.notes.add("Prefers a room near the parking lot.", important=True, guest_id=guests[0])
    with ctx.db.transaction():
        ctx.audit.log("setup.demo", "settings", None, "Generated demo data")
