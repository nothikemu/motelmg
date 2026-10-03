# MotelMG user guide

This guide walks through a typical day at the front desk. Everything here is
also discoverable in the application. Press **F1** for keyboard shortcuts, or
**Ctrl+K** to search for anything.

## Signing in

Each staff member has their own login, which an administrator creates under
**Staff**. The first time you sign in with a temporary password, MotelMG asks
you to choose your own. After five wrong passwords the account locks for five
minutes. **Ctrl+L** locks the screen when you step away, and an administrator
can make the screen lock automatically after a period of inactivity
(**Settings › Regional & appearance**).

What you can see and do depends on your role. For example, housekeepers see
the room board, housekeeping and maintenance, while front desk staff cannot
issue refunds or override rates.

## Morning: departures

1. Open the **Dashboard**. *Today's departures* lists everyone due out, and
   overdue guests are marked in red.
2. Double-click a departure (or select it and choose **Check out**). The
   check-out window shows the folio balance:
   - leaving **early**: unused nights are removed automatically, and you can
     charge an early-departure fee;
   - stayed **past the departure date**: the extra nights are posted;
   - **late check-out**: you can add the late check-out fee.
3. Take the payment in the same window, choose the method, and click
   **Check out**. The invoice is numbered automatically and opens for
   printing or saving as PDF.
4. The room is marked **dirty** and a cleaning task is created
   automatically.

If a guest has to settle up later (for example, a company that pays by
invoice), a manager can tick **Check out with an open balance**. The folio
then appears under **Billing › Outstanding balances**.

## Midday: housekeeping

- The **Housekeeping** page lists every open task. **Generate daily tasks**
  adds stayover service for occupied rooms.
- Select tasks, then click **Assign…** to give them to a housekeeper.
  Housekeepers click **Start** and then **Mark complete**.
- Supervisors open **Awaiting inspection** and choose **Pass inspection**, or
  **Fail** with a note; a failed room goes back to the housekeeper.
- A room whose next guest arrives today is flagged **Urgent**.

The **Room board** shows every room at once: green rooms are vacant and ready
to sell, blue are occupied, purple have an arrival today, amber need
cleaning, and orange or grey are out of order.

## Afternoon: arrivals

1. *Today's arrivals* on the dashboard lists who is expected. Double-click a
   guest to check them in.
2. The check-in window warns you about anything unusual:
   - the room is not clean yet. You can check the guest in anyway, or use
     **Change room**;
   - the guest arrived a day late, so the missed night is not charged;
   - the guest arrived before check-in time. You can charge the early
     check-in fee;
   - a note on the guest's profile is marked **Important**.
3. Record the guest's ID document. By default this is required before
   check-in, and the setting can be changed under **Settings › Front desk
   policies**.
4. Take the stay payment, or leave the amount empty to collect at check-out.

**Walk-ins:** click **Walk-in** (Ctrl+Shift+N) in the top bar. Find the
guest or create a new profile, choose the number of nights and a room, and
take payment. The guest is checked in straight away.

## Taking reservations

Click **New reservation** (Ctrl+N), or double-click an empty day on the
**Calendar**.

1. Search for a returning guest by name, phone, email or ID number, or click
   **New guest**. MotelMG warns you if the new profile looks like an
   existing one.
2. Choose the dates and the number of guests. The room list only shows rooms
   that are free for **every** night of the stay, so double-booking is
   impossible.
3. Pick a room and, if one applies, a discount. The summary shows the exact
   total, including taxes and automatic fees.
4. Save the booking. You can then record a deposit from the reservation
   window.

To change a booking, open it: double-click it anywhere, or press Ctrl+K and
type the confirmation number. The reservation window has buttons for
**Modify**, **Change room**, **Cancel**, **No-show** and more. Cancelling
releases the room straight away and lets you charge a cancellation fee and
refund the rest of the deposit.

### Moving a guest to another room

Open the reservation and click **Move room**. Choose a free room and give a
reason. You can keep the current rate or switch to the new room's rate.
Nights from today onward are charged to the new room, and the old room goes
to housekeeping.

## Billing

The **Folio** tab of a reservation lists every charge and payment.

- **Add charge:** pick an item from the catalog (pet fee, laundry, damage…)
  or type a custom charge. Tax is added automatically.
- **Take payment / Refund:** for cash payments, enter the amount received to
  see the change due.
- To correct a mistake, right-click a charge and choose **Void**. Room nights
  follow the stay dates, so to comp a night, use **More › Apply discount**.

The **Billing** page shows all transactions, outstanding balances and
invoices.

## Maintenance

Click **Report issue** on the Maintenance page or from the room board. Tick
**Take the room out of service** if the room can't be sold until the issue
is fixed. MotelMG lists any reservations booked into that room so you can
move them. When the ticket is resolved, the room returns to service and is
sent to housekeeping.

For longer closures, such as a renovation, use **Take out of order** on the
room board.

## Night audit checklist

- Look at the bell icon. Alerts list:
  - possible **no-shows**, which you can mark as no-show to release the room
    and charge a fee;
  - **unpaid balances** and **refunds due**;
  - **booking conflicts**.
- Run **Reports › Daily revenue** and **Payment history** for today, and
  print or export them.

## Backups

MotelMG backs up automatically every day; you can change this under
**Settings › Backup & restore**. For extra safety, set the backup folder to
a USB drive or a cloud-synced folder.

To restore a backup, select it and click **Restore selected…**. A safety
copy of the current data is saved first, and everyone is signed out.

## First-time setup checklist (administrators)

1. **Settings › Property**: name, address and phone, which appear on
   invoices.
2. **Settings › Rooms & rates**: room types, rates and rooms.
3. **Settings › Taxes, fees & discounts**: tax rates; the amounts for early
   check-in, late check-out, cancellation and no-show fees; and any
   automatic fees.
4. **Settings › Front desk policies**: check-in and check-out times, the
   inspection requirement, and the ID requirement.
5. **Staff**: create an account for each team member with the right role.
