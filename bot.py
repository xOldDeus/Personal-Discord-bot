import discord
from discord import app_commands
from discord.ext import tasks
import json
from datetime import datetime, timedelta, timezone
import os
import pytz
import threading
from flask import Flask

# --- Flask Keep-Alive for Render Web Service ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

# --- Discord Bot Setup ---
intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

REMINDERS_FILE = 'reminders.json'
EASTERN = pytz.timezone("US/Eastern")

def load_reminders():
    try:
        with open(REMINDERS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_reminders(reminders):
    with open(REMINDERS_FILE, 'w') as f:
        json.dump(reminders, f)

def parse_datetime_eastern(date_str, time_str):
    # Convert user input (Eastern) to UTC
    dt_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    dt_eastern = EASTERN.localize(dt_naive)
    dt_utc = dt_eastern.astimezone(timezone.utc)
    return dt_utc

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    try:
        synced = await tree.sync()
        print(f'Synced {len(synced)} slash commands.')
    except Exception as e:
        print(f'Error syncing commands: {e}')
    reminder_check.start()

@tree.command(name="reminder", description="Set a reminder in your local (EST) time.")
@app_commands.describe(
    date="Date (YYYY-MM-DD, EST time)",
    time="Time (24hr HH:MM, EST time)",
    text="What should I remind you about?",
    notify_before="When to remind you before the event"
)
@app_commands.choices(notify_before=[
    app_commands.Choice(name="1 minute before", value="1"),
    app_commands.Choice(name="5 minutes before", value="5"),
    app_commands.Choice(name="10 minutes before", value="10"),
    app_commands.Choice(name="30 minutes before", value="30"),
    app_commands.Choice(name="1 hour before", value="60"),
    app_commands.Choice(name="6 hours before", value="360"),
    app_commands.Choice(name="12 hours before", value="720"),
    app_commands.Choice(name="1 day before", value="1440"),
])
async def reminder(
    interaction: discord.Interaction,
    date: str,
    time: str,
    text: str,
    notify_before: app_commands.Choice[str]
):
    # Convert to UTC
    try:
        dt_utc = parse_datetime_eastern(date, time)
        dt_str_utc = dt_utc.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        await interaction.response.send_message(
            "Invalid date/time format! Use YYYY-MM-DD for date and 24hr HH:MM for time.",
            ephemeral=True)
        return
    reminders = load_reminders()
    reminders.append({
        "user_id": interaction.user.id,
        "text": text,
        "time_utc": dt_str_utc,
        "notify_before_min": int(notify_before.value)
    })
    save_reminders(reminders)
    eastern_dt_str = dt_utc.astimezone(EASTERN).strftime("%Y-%m-%d %I:%M %p")
    notify_str = f"{notify_before.name}"
    await interaction.response.send_message(
        f"Reminder set for **{eastern_dt_str} (EST time)**: {text}\n"
        f"You'll also get notified: **{notify_str}**",
        ephemeral=True)

@tree.command(name="reminders", description="List your reminders.")
async def reminders(interaction: discord.Interaction):
    reminders = load_reminders()
    user_reminders = [r for r in reminders if r['user_id'] == interaction.user.id]
    if not user_reminders:
        await interaction.response.send_message("You have no reminders.", ephemeral=True)
    else:
        msg = ""
        for idx, r in enumerate(user_reminders, 1):
            # Show time in EST time for clarity
            event_time = datetime.strptime(r['time_utc'], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            local_time = event_time.astimezone(EASTERN)
            time_str = local_time.strftime("%Y-%m-%d %I:%M %p")
            nb = r['notify_before_min']
            if nb < 60:
                nb_str = f"{nb} min"
            elif nb == 60:
                nb_str = "1 hour"
            elif nb < 1440:
                nb_str = f"{nb // 60} hours"
            else:
                nb_str = "1 day"
            msg += f"{idx}. {time_str}: {r['text']} | Notify: {nb_str} before\n"
        await interaction.response.send_message(f"Your reminders:\n{msg}", ephemeral=True)

@tree.command(name="servertime", description="See the bot's current UTC and EST time.")
async def servertime(interaction: discord.Interaction):
    now_utc = datetime.utcnow()
    now_et = datetime.now(EASTERN)
    await interaction.response.send_message(
        f"Server time (UTC): {now_utc.strftime('%Y-%m-%d %H:%M')}\n"
        f"EST time: {now_et.strftime('%Y-%m-%d %I:%M %p')}",
        ephemeral=True
    )

@tasks.loop(minutes=1)
async def reminder_check():
    reminders = load_reminders()
    now_utc = datetime.utcnow().replace(second=0, microsecond=0, tzinfo=timezone.utc)
    to_remove = []
    for idx, r in enumerate(reminders):
        dt_utc = datetime.strptime(r['time_utc'], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        user = await bot.fetch_user(r['user_id'])
        notify_time = dt_utc - timedelta(minutes=r['notify_before_min'])

        print(f"Now (UTC): {now_utc}, Notify time: {notify_time}, Main event: {dt_utc}")

        # Notify before
        if notify_time == now_utc:
            if user:
                local_time = dt_utc.astimezone(EASTERN).strftime("%Y-%m-%d %I:%M %p")
                try:
                    await user.send(
                        f"⏰ Heads up! You have an upcoming event: **{r['text']}** at **{local_time} (EST time)**"
                    )
                except Exception as e:
                    print(f"Could not send pre-reminder DM: {e}")
        # Main event
        if dt_utc == now_utc:
            if user:
                local_time = dt_utc.astimezone(EASTERN).strftime("%Y-%m-%d %I:%M %p")
                try:
                    await user.send(
                        f"🔔 Reminder: **{r['text']}** is happening now! ({local_time} EST time)"
                    )
                except Exception as e:
                    print(f"Could not send main reminder DM: {e}")
            to_remove.append(idx)
    # Remove sent reminders
    reminders = [r for i, r in enumerate(reminders) if i not in to_remove]
    save_reminders(reminders)

keep_alive()
bot.run(os.environ['DISCORD_TOKEN'])
