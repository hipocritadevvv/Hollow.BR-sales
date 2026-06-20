import discord
from discord.ext import commands
import os
import asyncpg
from datetime import datetime

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
BOT_TOKEN          = os.environ["TOKEN"]
ADMIN_ROLE_ID      = 1508180351418372236
LOG_CHANNEL_ID     = int(os.environ["LOG_CHANNEL_ID"])
TICKET_CATEGORY_ID = int(os.environ["TICKET_CATEGORY_ID"])
DATABASE_URL       = os.environ["DATABASE_URL"]
PIX_KEY            = "677.662.427.4267"
PIX_QR_URL         = "https://i.pinimg.com/736x/64/59/9c/64599cb7b3f0c3ac87b6ce976fa9269d.jpg"
# ─────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ══════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════

async def init_db():
    bot.db = await asyncpg.connect(DATABASE_URL)
    await bot.db.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id SERIAL PRIMARY KEY,
            product TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE
        )
    """)

async def db_add_key(product: str, key: str):
    await bot.db.execute(
        "INSERT INTO stock (product, key) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        product, key
    )

async def db_get_keys(product: str) -> list:
    rows = await bot.db.fetch("SELECT key FROM stock WHERE product=$1", product)
    return [r["key"] for r in rows]

async def db_pop_key(product: str) -> str | None:
    row = await bot.db.fetchrow(
        "DELETE FROM stock WHERE id = (SELECT id FROM stock WHERE product=$1 LIMIT 1) RETURNING key",
        product
    )
    return row["key"] if row else None

async def db_remove_key(key: str) -> str | None:
    row = await bot.db.fetchrow(
        "DELETE FROM stock WHERE key=$1 RETURNING product", key
    )
    return row["product"] if row else None

async def db_count(product: str) -> int:
    return await bot.db.fetchval("SELECT COUNT(*) FROM stock WHERE product=$1", product)

async def db_all_stock() -> dict:
    rows = await bot.db.fetch("SELECT product, key FROM stock ORDER BY product")
    result = {}
    for r in rows:
        result.setdefault(r["product"], []).append(r["key"])
    return result


# ══════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════

def has_admin_role():
    async def predicate(ctx):
        return any(r.id == ADMIN_ROLE_ID for r in ctx.author.roles)
    return commands.check(predicate)

async def send_log(guild: discord.Guild, embed: discord.Embed):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed)

def log_embed(title: str, color: discord.Color, **fields) -> discord.Embed:
    em = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    for name, value in fields.items():
        em.add_field(name=name, value=value, inline=False)
    em.set_footer(text="Sales Bot • Logs")
    return em


# ══════════════════════════════════════════
#  VIEWS
# ══════════════════════════════════════════

async def open_ticket(interaction: discord.Interaction, product: str, duration: str):
    guild = interaction.guild

    # Check stock before opening ticket (key = Product_Duration)
    stock_key = f"{product}_{duration}"
    count = await db_count(stock_key)
    if count == 0:
        em = discord.Embed(
            title="❌ Out of Stock",
            description=f"Sorry, **{product} {duration}** is currently out of stock.\nPlease try again later or contact support.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=em, ephemeral=True)
        return

    category = guild.get_channel(TICKET_CATEGORY_ID)
    ticket_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")

    existing = discord.utils.get(guild.text_channels, name=ticket_name)
    if existing:
        await interaction.response.send_message(
            f"❌ You already have an open ticket: {existing.mention}", ephemeral=True
        )
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }
    admin_role = guild.get_role(ADMIN_ROLE_ID)
    if admin_role:
        overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    channel = await guild.create_text_channel(
        name=ticket_name,
        overwrites=overwrites,
        category=category,
    )

    em = discord.Embed(
        title="🛒 New Order",
        description=(
            f"Hello {interaction.user.mention}! Thank you for your order.\n\n"
            f"**Product:** `{product}`\n"
            f"**Duration:** `{duration}`\n\n"
            "Please send your **payment proof** here.\n"
            "A staff member will review and approve your purchase shortly.\n\n"
            f"**PIX Key:** `{PIX_KEY}`"
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow(),
    )
    em.set_image(url=PIX_QR_URL)
    em.set_footer(text="Use !fechar to close this ticket.")
    await channel.send(embed=em)

    await interaction.response.send_message(
        f"✅ Your ticket has been opened: {channel.mention}", ephemeral=True
    )

    log = log_embed(
        "🎫 Ticket Opened",
        discord.Color.green(),
        User=f"{interaction.user} (`{interaction.user.id}`)",
        Product=product,
        Duration=duration,
        Channel=channel.mention,
    )
    await send_log(guild, log)


class DurationSelect(discord.ui.Select):
    def __init__(self, product: str):
        self.product = product
        options = [
            discord.SelectOption(label="Weekly",   emoji="📅", description="7-day access"),
            discord.SelectOption(label="Monthly",  emoji="🗓️", description="30-day access"),
            discord.SelectOption(label="Lifetime", emoji="♾️", description="Permanent access"),
        ]
        super().__init__(placeholder="Select a duration...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await open_ticket(interaction, self.product, self.values[0])


class DurationView(discord.ui.View):
    def __init__(self, product: str):
        super().__init__(timeout=120)
        self.add_item(DurationSelect(product))


class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Plus",    emoji="⭐", description="Best version, access to everything"),
            discord.SelectOption(label="Premium", emoji="💎", description="Great version, just below Plus"),
        ]
        super().__init__(placeholder="Select a product...", options=options)

    async def callback(self, interaction: discord.Interaction):
        product = self.values[0]
        em = discord.Embed(
            title=f"⏱️ Choose Duration — {product}",
            description="Now select how long you want your license:",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=em, view=DurationView(product), ephemeral=True)


class ProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Buy", style=discord.ButtonStyle.success, emoji="🛒", custom_id="buy_button")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        em = discord.Embed(
            title="🛍️ Choose a Product",
            description="Select the plan you want to purchase:",
            color=discord.Color.gold(),
        )
        view = discord.ui.View(timeout=120)
        view.add_item(ProductSelect())
        await interaction.response.send_message(embed=em, view=view, ephemeral=True)


# ══════════════════════════════════════════
#  EVENTS
# ══════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(ProductView())
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")


# ══════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════

@bot.command()
@has_admin_role()
async def painel(ctx):
    em = discord.Embed(
        title="Hollow.Br Sales",
        description=(
            "Welcome to Hollow.Br\n"
            "Choose your plan below to open a ticket and complete your purchase.\n\n"
            "⭐ **Plus** — Best version, access to everything.\n"
            "💎 **Premium** — Great version, just below the Plus version.\n\n"
            "After selecting a plan, choose your preferred duration."
        ),
        color=discord.Color.gold(),
        timestamp=datetime.utcnow(),
    )
    em.set_footer(text="Click below to start your order!")
    await ctx.send(embed=em, view=ProductView())
    await ctx.message.delete()


@bot.command()
@has_admin_role()
async def fechar(ctx):
    if "ticket-" not in ctx.channel.name:
        await ctx.send("❌ This command can only be used inside a ticket channel.")
        return

    em = discord.Embed(
        title="🔒 Ticket Closing",
        description="This ticket will be deleted in **5 seconds**.",
        color=discord.Color.red(),
    )
    await ctx.send(embed=em)

    log = log_embed(
        "🔒 Ticket Closed",
        discord.Color.red(),
        Channel=ctx.channel.name,
        ClosedBy=f"{ctx.author} (`{ctx.author.id}`)",
    )
    await send_log(ctx.guild, log)

    import asyncio
    await asyncio.sleep(5)
    await ctx.channel.delete()


@bot.command()
@has_admin_role()
async def aprovar(ctx):
    if "ticket-" not in ctx.channel.name:
        await ctx.send("❌ This command can only be used inside a ticket channel.")
        return

    ticket_username = ctx.channel.name.replace("ticket-", "")
    buyer = discord.utils.find(
        lambda m: m.name.lower().replace(" ", "-") == ticket_username,
        ctx.guild.members,
    )

    if not buyer:
        await ctx.send("❌ Could not find the buyer. Please deliver the key manually.")
        return

    product, duration = "Unknown", "Unknown"
    async for msg in ctx.channel.history(oldest_first=True, limit=5):
        if msg.author == bot.user and msg.embeds:
            emb = msg.embeds[0]
            for field in emb.description.split("\n") if emb.description else []:
                if "**Product:**" in field:
                    product = field.split("`")[1]
                if "**Duration:**" in field:
                    duration = field.split("`")[1]
            break

    key = await db_pop_key(f"{product}_{duration}")
    if not key:
        await ctx.send(f"❌ No stock available for **{product} {duration}**.")
        return

    remaining = await db_count(f"{product}_{duration}")

    try:
        dm_em = discord.Embed(
            title="✅ Purchase Approved!",
            description=(
                f"Your order has been approved! Here is your key:\n\n"
                f"**Product:** `{product}`\n"
                f"**Duration:** `{duration}`\n"
                f"**Key:** ||`{key}`||\n\n"
                "Thank you for your purchase! If you need help, open a new ticket."
            ),
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await buyer.send(embed=dm_em)
        await ctx.send(f"✅ Key delivered to {buyer.mention} via DM. Remaining stock for **{product}**: `{remaining}`.\n🔒 This ticket will be deleted in **5 seconds**.")
    except discord.Forbidden:
        await ctx.send(f"⚠️ Could not DM {buyer.mention}. Key: ||`{key}`||\n🔒 This ticket will be deleted in **5 seconds**.")

    log = log_embed(
        "✅ Purchase Approved",
        discord.Color.green(),
        Buyer=f"{buyer} (`{buyer.id}`)",
        Product=product,
        Duration=duration,
        ApprovedBy=f"{ctx.author} (`{ctx.author.id}`)",
        RemainingStock=str(remaining),
    )
    await send_log(ctx.guild, log)

    import asyncio
    await asyncio.sleep(5)
    await ctx.channel.delete()


@bot.command()
@has_admin_role()
async def addstock(ctx, product: str, *, key: str):
    await db_add_key(product, key)
    count = await db_count(product)
    await ctx.send(f"✅ Key added to **{product}**. Total keys: `{count}`.")

    log = log_embed(
        "📦 Stock Added",
        discord.Color.blurple(),
        Product=product,
        Key=f"||`{key}`||",
        AddedBy=f"{ctx.author} (`{ctx.author.id}`)",
        TotalKeys=str(count),
    )
    await send_log(ctx.guild, log)


@bot.command(name="stock")
@has_admin_role()
async def view_stock(ctx, product: str = None):
    if product:
        keys = await db_get_keys(product)
        em = discord.Embed(
            title=f"📦 Stock — {product}",
            description=f"`{len(keys)}` key(s) available." if keys else "❌ No keys available.",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if keys:
            em.add_field(
                name="Keys",
                value="\n".join([f"||`{k}`||" for k in keys]),
                inline=False,
            )
        await ctx.send(embed=em)
    else:
        all_stock = await db_all_stock()
        em = discord.Embed(
            title="📦 Full Stock Overview",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if not all_stock:
            em.description = "No products in stock."
        else:
            for prod, keys in all_stock.items():
                em.add_field(name=prod, value=f"`{len(keys)}` key(s)", inline=True)
        await ctx.send(embed=em)


@bot.command()
@has_admin_role()
async def removerstock(ctx, *, key: str):
    product = await db_remove_key(key)
    if product:
        remaining = await db_count(product)
        await ctx.send(f"✅ Key removed from **{product}**. Remaining: `{remaining}`.")
        log = log_embed(
            "🗑️ Stock Removed",
            discord.Color.orange(),
            Product=product,
            Key=f"||`{key}`||",
            RemovedBy=f"{ctx.author} (`{ctx.author.id}`)",
            RemainingKeys=str(remaining),
        )
        await send_log(ctx.guild, log)
    else:
        await ctx.send("❌ Key not found in any product's stock.")


# ══════════════════════════════════════════
#  ERROR HANDLING
# ══════════════════════════════════════════

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You don't have permission to use this command.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`.", delete_after=8)
    else:
        raise error


bot.run(BOT_TOKEN)
