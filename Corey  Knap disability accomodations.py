from datetime import datetime, timedelta

# Original due date (Sunday example)
due_date_str = "2026-02-22"  # YYYY-MM-DD for the Sunday due date
due_date = datetime.strptime(due_date_str, "%Y-%m-%d")

# Add 2 days
new_due_date = due_date + timedelta(days=2)

message = (
    "Sorry, I utilized my accommodations. "
    f"May I have until {new_due_date.strftime('%A')} "
    f"({new_due_date.strftime('%m/%d/%Y')}) for what's due Sunday?"
)

print(message)