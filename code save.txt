import discord
from discord.ext import commands, tasks
from discord import app_commands
from pymongo import MongoClient
import requests
import os
from dotenv import load_dotenv
import re
import asyncio

# Load environment variables
load_dotenv()

# Environment variables
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
LEARNWORLDS_TOKEN = os.getenv("LEARNWORLDS_TOKEN")
LW_CLIENT_ID = os.getenv("LW_CLIENT_ID")
LEARNWORLDS_API_BASE_URL = os.getenv("LEARNWORLDS_API_BASE_URL", "https://courses.altacademy.org/admin/api/v2/users")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# Enhanced Role Mapping
ROLE_MAPPING = {
    "Plus User": "Plus User",
    "Exam Pass 25": "Exam Pass 25",
    "Solo Pass": "Solo Pass",
    "Free": "Free",
    "O level": "O level",
    "Chemistry": "Chemistry",
    "Physics": "Physics",
    "Economics": "Economics",
    "Business": "Business",
    "Accounts": "Accounts",
    "Biology": "Biology",
    "Maths": "Maths",
    "Psycology": "Psycology",
}

# Subject Role Mapping
SUBJECT_ROLE_MAPPING = {
    "Chemistry": "Chemistry",
    "Physics": "Physics",
    "Economics": "Economics",
    "Business": "Business",
    "Accounts": "Accounts",
    "Biology": "Biology",
    "Maths": "Maths",
    "Psycology": "Psycology",
}

# MongoDB Connection
try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["discord_bot"]
    users_collection = db["users"]
    print("[SUCCESS] Connected to MongoDB")
except Exception as e:
    print(f"[ERROR] MongoDB connection failed: {e}")

class BotClient(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        try:
            await self.tree.sync()
            print("[SUCCESS] Slash commands synced successfully")
        except Exception as e:
            print(f"[ERROR] Failed to sync commands: {e}")

bot = BotClient()

def fetch_user_details(email: str) -> dict:
    """Fetch user details from LearnWorlds including tags and subjects."""
    try:
        url = f"{LEARNWORLDS_API_BASE_URL}/{email}"
        headers = {
            "Authorization": f"Bearer {LEARNWORLDS_TOKEN}",
            "Lw-Client": LW_CLIENT_ID,
            "Accept": "application/json"
        }
        
        response = requests.get(url, headers=headers)
        print(f"[DEBUG] API Response Status: {response.status_code}")
        print(f"[DEBUG] API Response: {response.text}")

        if response.status_code == 200:
            user_data = response.json()
            return {
                'tags': user_data.get('tags', []),
                'subjects': user_data.get('fields', {}).get('cf_subjects', '').split(', '),
                'raw_data': user_data
            }
        else:
            print(f"[ERROR] API request failed: {response.status_code}")
            return {'tags': [], 'subjects': [], 'raw_data': None}
    except Exception as e:
        print(f"[ERROR] Failed to fetch user details: {e}")
        return {'tags': [], 'subjects': [], 'raw_data': None}

async def create_role_if_not_exists(guild, role_name):
    """Create a role if it doesn't exist in the server."""
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            role = await guild.create_role(name=role_name)
            print(f"[SUCCESS] Created new role: {role_name}")
        except Exception as e:
            print(f"[ERROR] Failed to create role {role_name}: {e}")
    return role

async def update_member_roles(member, user_details):
    """Update member roles based on tags and subjects."""
    try:
        # Get all possible roles from both mappings
        all_mappings = {**ROLE_MAPPING, **SUBJECT_ROLE_MAPPING}
        
        # Get current roles that are in our mapping
        current_roles = [role for role in member.roles 
                        if role.name in all_mappings.values()]
        
        # Calculate new roles from tags
        new_role_names = []
        
        # Add roles from tags
        for tag in user_details['tags']:
            if tag in ROLE_MAPPING:
                new_role_names.append(ROLE_MAPPING[tag])
        
        # Add roles from subjects
        for subject in user_details['subjects']:
            subject = subject.strip()  # Remove any whitespace
            if subject in SUBJECT_ROLE_MAPPING:
                new_role_names.append(SUBJECT_ROLE_MAPPING[subject])
        
        # Remove roles that are no longer applicable
        roles_to_remove = [role for role in current_roles 
                          if role.name not in new_role_names]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
            print(f"[INFO] Removed roles from {member.name}: {[r.name for r in roles_to_remove]}")
        
        # Add new roles
        assigned_roles = []
        for role_name in new_role_names:
            role = await create_role_if_not_exists(member.guild, role_name)
            if role and role not in member.roles:
                await member.add_roles(role)
                assigned_roles.append(role_name)
                print(f"[SUCCESS] Added role {role_name} to {member.name}")
        
        return assigned_roles
    except Exception as e:
        print(f"[ERROR] Failed to update roles: {e}")
        return []

@bot.event
async def on_member_join(member):
    """Handle new member joining the server."""
    try:
        await member.send(
            "Welcome to the server! Please reply with your LearnWorlds email address to verify your account."
        )

        def check(m):
            return m.author == member and isinstance(m.channel, discord.DMChannel)

        email_message = await bot.wait_for("message", check=check, timeout=300)
        email = email_message.content.strip().lower()

        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            await member.send("❌ Invalid email format. Please try again with a valid email address.")
            return

        # Fetch user details including tags and subjects
        user_details = fetch_user_details(email)
        
        if not user_details['tags'] and not user_details['subjects']:
            await member.send("No LearnWorlds data found for your email. Please contact an administrator.")
            return

        # Assign roles based on tags and subjects
        assigned_roles = await update_member_roles(member, user_details)

        # Save to MongoDB
        users_collection.update_one(
            {"_id": member.id},
            {
                "$set": {
                    "learnworlds_email": email,
                    "discord_tag": str(member),
                    "tags": user_details['tags'],
                    "subjects": user_details['subjects'],
                    "assigned_roles": assigned_roles,
                    "raw_data": user_details['raw_data']
                }
            },
            upsert=True
        )

        # Create and send confirmation embed
        embed = discord.Embed(
            title="✅ Verification Complete",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Email",
            value=email,
            inline=False
        )
        
        if user_details['tags']:
            embed.add_field(
                name="LearnWorlds Tags",
                value="\n".join([f"• {tag}" for tag in user_details['tags']]),
                inline=False
            )
            
        if user_details['subjects']:
            embed.add_field(
                name="Subjects",
                value="\n".join([f"• {subject}" for subject in user_details['subjects'] if subject]),
                inline=False
            )
            
        if assigned_roles:
            embed.add_field(
                name="Assigned Roles",
                value="\n".join([f"• {role}" for role in assigned_roles]),
                inline=False
            )
        
        await member.send(embed=embed)
        print(f"[SUCCESS] Completed verification for {member.name}")

    except asyncio.TimeoutError:
        await member.send("Verification timeout. Please use the /verify command to verify your email.")
    except Exception as e:
        print(f"[ERROR] Error during member join: {e}")
        await member.send("An error occurred during verification. Please contact an administrator.")

@bot.tree.command(name="verify", description="Verify your email address")
async def verify(interaction: discord.Interaction):
    """Manual verification command."""
    try:
        await interaction.response.send_message(
            "Please check your DMs for verification instructions.",
            ephemeral=True
        )
        
        await interaction.user.send(
            "Please reply with your LearnWorlds email address to verify your account."
        )

        def check(m):
            return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

        email_message = await bot.wait_for("message", check=check, timeout=300)
        email = email_message.content.strip().lower()

        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            await interaction.user.send("❌ Invalid email format. Please try again with a valid email address.")
            return

        user_details = fetch_user_details(email)
        
        if not user_details['tags'] and not user_details['subjects']:
            await interaction.user.send("No LearnWorlds data found for your email. Please contact an administrator.")
            return

        assigned_roles = await update_member_roles(interaction.user, user_details)

        users_collection.update_one(
            {"_id": interaction.user.id},
            {
                "$set": {
                    "learnworlds_email": email,
                    "discord_tag": str(interaction.user),
                    "tags": user_details['tags'],
                    "subjects": user_details['subjects'],
                    "assigned_roles": assigned_roles,
                    "raw_data": user_details['raw_data']
                }
            },
            upsert=True
        )

        embed = discord.Embed(
            title="✅ Verification Complete",
            color=discord.Color.green()
        )
        
        embed.add_field(name="Email", value=email, inline=False)
        
        if user_details['tags']:
            embed.add_field(
                name="LearnWorlds Tags",
                value="\n".join([f"• {tag}" for tag in user_details['tags']]),
                inline=False
            )
            
        if user_details['subjects']:
            embed.add_field(
                name="Subjects",
                value="\n".join([f"• {subject}" for subject in user_details['subjects'] if subject]),
                inline=False
            )
            
        if assigned_roles:
            embed.add_field(
                name="Assigned Roles",
                value="\n".join([f"• {role}" for role in assigned_roles]),
                inline=False
            )
        
        await interaction.user.send(embed=embed)

    except asyncio.TimeoutError:
        await interaction.user.send("Verification timeout. Please try again.")
    except Exception as e:
        print(f"[ERROR] Verification failed: {e}")
        await interaction.user.send("An error occurred during verification. Please contact an administrator.")

@bot.event
async def on_ready():
    """Bot startup complete."""
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="for new members"
        )
    )
    print(f"[SUCCESS] Bot has connected as {bot.user}")
    print(f"[INFO] Connected to {len(bot.guilds)} server(s):")
    for guild in bot.guilds:
        print(f" - {guild.name} (ID: {guild.id})")
    print("[INFO] Bot is ready and operational")

# Run the bot
if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
