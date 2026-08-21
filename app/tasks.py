import re
from calendar import month_name
from datetime import date, timedelta

import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone
from groq import Groq

from .models import Expense, Category

logger = logging.getLogger(__name__)


# =========================================================
# BASIC HELPERS
# =========================================================

def format_money(amount):
    """Format a number as Indian Rupees."""
    return f"₹{float(amount or 0):,.2f}"


def get_groq_client():
    """Create the Groq client."""
    api_key = getattr(settings, "GROQ_API_KEY", None)

    if not api_key:
        raise ValueError("Groq API key is not configured.")

    return Groq(api_key=api_key)


def clean_ai_response(text):
    """
    Remove model reasoning / <think> blocks while
    preserving the actual answer.
    """

    if not text:
        return ""

    text = str(text).strip()

    # Remove complete <think>...</think> blocks.
    text = re.sub(
        r"<think>.*?</think>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Handle an unclosed thinking block.
    text = re.sub(
        r"<think>.*$",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove common standalone reasoning headers.
    text = re.sub(
        r"^\s*(thinking|analysis|reasoning)\s*:.*$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Remove excessive blank lines.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


# =========================================================
# CASUAL CONVERSATION
# =========================================================

def handle_casual_message(question):
    """
    Handle very simple conversational messages locally.

    This avoids wasting a Groq request on greetings,
    thanks, and goodbyes.
    """

    text = question.lower().strip()

    normalized = re.sub(
        r"[^\w\s]",
        "",
        text,
    )

    greetings = {
        "hi",
        "hello",
        "hey",
        "heyy",
        "heyyy",
        "hiya",
        "yo",
        "sup",
        "whats up",
        "good morning",
        "good afternoon",
        "good evening",
    }

    if normalized in greetings:
        return (
            "Hey! 👋 I'm Finch. "
            "Ask me anything about your finances."
        )

    thanks = {
        "thanks",
        "thank you",
        "thx",
        "ty",
        "thanks finch",
        "thank you finch",
    }

    if normalized in thanks:
        return "You're welcome! 😊"

    goodbyes = {
        "bye",
        "goodbye",
        "see you",
        "see ya",
        "later",
    }

    if normalized in goodbyes:
        return "See you later! 👋"

    return None


# =========================================================
# DATE HANDLING
# =========================================================

def get_date_range(question):
    """
    Determine the date range requested by the user.

    Returns:
        (start_date, end_date, description)
    """

    today = timezone.localdate()
    question_lower = question.lower()

    # -----------------------------------------------------
    # This year
    # -----------------------------------------------------

    if "this year" in question_lower:
        return (
            date(today.year, 1, 1),
            today,
            str(today.year),
        )

    # -----------------------------------------------------
    # Last year
    # -----------------------------------------------------

    if "last year" in question_lower:
        return (
            date(today.year - 1, 1, 1),
            date(today.year - 1, 12, 31),
            str(today.year - 1),
        )

    # -----------------------------------------------------
    # This month
    # -----------------------------------------------------

    if "this month" in question_lower:
        return (
            date(today.year, today.month, 1),
            today,
            month_name[today.month],
        )

    # -----------------------------------------------------
    # Last month
    # -----------------------------------------------------

    if "last month" in question_lower:

        if today.month == 1:
            year = today.year - 1
            month = 12
        else:
            year = today.year
            month = today.month - 1

        next_month = (
            date(year + 1, 1, 1)
            if month == 12
            else date(year, month + 1, 1)
        )

        last_day = (
            next_month - timedelta(days=1)
        ).day

        return (
            date(year, month, 1),
            date(year, month, last_day),
            month_name[month],
        )

    # -----------------------------------------------------
    # Explicit month names
    # -----------------------------------------------------

    months = {
        name.lower(): number
        for number, name in enumerate(month_name)
        if name
    }

    for name, month_number in months.items():

        if name in question_lower:

            year_match = re.search(
                r"\b(20\d{2})\b",
                question_lower,
            )

            year = (
                int(year_match.group(1))
                if year_match
                else today.year
            )

            next_month = (
                date(year + 1, 1, 1)
                if month_number == 12
                else date(year, month_number + 1, 1)
            )

            last_day = (
                next_month - timedelta(days=1)
            ).day

            return (
                date(year, month_number, 1),
                date(year, month_number, last_day),
                f"{name.title()} {year}",
            )

    return None, None, None


# =========================================================
# CATEGORY HANDLING
# =========================================================

def find_category(question, user):
    """
    Find a category mentioned in the question.

    NOTE: Category is NOT scoped to a user in this schema
    (it has no `user` field), so this looks across all
    categories rather than filtering by owner.
    """

    question_lower = question.lower()

    categories = Category.objects.all()

    # Longest names first so that, for example,
    # "online shopping" is checked before "shopping".
    categories = sorted(
        categories,
        key=lambda category: len(category.name or ""),
        reverse=True,
    )

    for category in categories:

        category_name = (
            category.name.strip().lower()
            if category.name
            else ""
        )

        if (
            category_name
            and category_name in question_lower
        ):
            return category

    return None


# =========================================================
# EXACT DATABASE QUESTIONS
# =========================================================

def answer_simple_financial_question(question, user):
    """
    Answer questions that Django can calculate exactly.

    Returns:
        Answer string, or None if Groq should handle it.
    """

    question_lower = question.lower()

    # -----------------------------------------------------
    # Advice questions must NOT be treated as calculations.
    # -----------------------------------------------------

    advice_words = [
        "how can i",
        "how do i",
        "how should i",
        "what should i",
        "what can i",
        "where can i",
        "how could i",
        "tips",
        "advice",
        "recommend",
        "recommendation",
        "reduce",
        "lower",
        "save",
        "saving",
        "cut back",
        "cut down",
        "improve",
        "budget better",
        "predict",
        "prediction",
        "forecast",
        "estimate",
        "projection",
        "project",
        "expect",
        "will i spend",
    ]

    if any(
        word in question_lower
        for word in advice_words
    ):
        return None

    # -----------------------------------------------------
    # Expense / income detection.
    # -----------------------------------------------------

    expense_words = [
        "spend",
        "spent",
        "expense",
        "expenses",
        "spending",
    ]

    income_words = [
        "income",
        "earned",
        "earn",
        "salary",
        "received",
    ]

    is_expense_question = any(
        word in question_lower
        for word in expense_words
    )

    is_income_question = any(
        word in question_lower
        for word in income_words
    )

    if not is_expense_question and not is_income_question:
        return None

    # -----------------------------------------------------
    # Date range.
    # -----------------------------------------------------

    start_date, end_date, period = get_date_range(
        question,
    )

    date_filter = {}

    if start_date and end_date:
        date_filter = {
            "date__gte": start_date,
            "date__lte": end_date,
        }

    category = find_category(
        question,
        user,
    )

    # =====================================================
    # EXPENSE
    # =====================================================

    if is_expense_question:

        expenses = Expense.objects.filter(
            user=user,
            **date_filter,
        )

        if category:
            expenses = expenses.filter(
                category=category,
            )

        total = (
            expenses.aggregate(
                total=Sum("amount"),
            )["total"]
            or 0
        )

        count = expenses.count()

        if period:

            if category:
                return (
                    f"You spent {format_money(total)} "
                    f"on {category.name} during {period}."
                )

            return (
                f"You spent {format_money(total)} "
                f"on expenses during {period}."
            )

        if category:

            return (
                f"You've spent {format_money(total)} "
                f"on {category.name}."
            )

        return (
            f"You've spent {format_money(total)} "
            f"across {count} expenses."
        )

    # =====================================================
    # INCOME
    # =====================================================

    if is_income_question:

        incomes = Income.objects.filter(
            user=user,
            **date_filter,
        )

        total = (
            incomes.aggregate(
                total=Sum("amount"),
            )["total"]
            or 0
        )

        count = incomes.count()

        if period:
            return (
                f"You received {format_money(total)} "
                f"in income during {period}."
            )

        return (
            f"You've received {format_money(total)} "
            f"across {count} income transactions."
        )

    return None


# =========================================================
# FINANCIAL CONTEXT FOR GROQ
# =========================================================

def build_financial_context(user):
    """
    Build useful financial context for Groq.

    Includes:
    - Recent transactions
    - Category totals
    - Overall totals

    This gives Groq enough information to answer
    advice questions without dumping the entire database
    into the prompt.
    """

    # -----------------------------------------------------
    # Recent expenses
    # -----------------------------------------------------

    expenses = (
        Expense.objects
        .select_related("category")
        .filter(user=user)
        .order_by("-date", "-id")[:30]
    )

    # -----------------------------------------------------
    # Recent income
    # -----------------------------------------------------

    incomes = (
        Income.objects
        .select_related("category")
        .filter(user=user)
        .order_by("-date", "-id")[:15]
    )

    # -----------------------------------------------------
    # Expense category totals
    # -----------------------------------------------------

    category_totals = (
        Expense.objects
        .filter(user=user)
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )

    # -----------------------------------------------------
    # Format recent expenses
    # -----------------------------------------------------

    expense_lines = []

    for expense in expenses:

        category = (
            expense.category.name
            if expense.category
            else "Uncategorized"
        )

        expense_lines.append(
            f"- {expense.date}: "
            f"{format_money(expense.amount)} | "
            f"{expense.title} | "
            f"Category: {category}"
        )

    # -----------------------------------------------------
    # Format recent income
    # -----------------------------------------------------

    income_lines = []

    for income in incomes:

        category = (
            income.category.name
            if income.category
            else "Uncategorized"
        )

        income_lines.append(
            f"- {income.date}: "
            f"{format_money(income.amount)} | "
            f"{income.title} | "
            f"Category: {category}"
        )

    # -----------------------------------------------------
    # Format category totals
    # -----------------------------------------------------

    category_lines = []

    for item in category_totals:

        category_name = (
            item["category__name"]
            or "Uncategorized"
        )

        category_lines.append(
            f"- {category_name}: "
            f"{format_money(item['total'])}"
        )

    # -----------------------------------------------------
    # Overall totals
    # -----------------------------------------------------

    total_expenses = (
        Expense.objects
        .filter(user=user)
        .aggregate(total=Sum("amount"))["total"]
        or 0
    )

    total_income = (
        Income.objects
        .filter(user=user)
        .aggregate(total=Sum("amount"))["total"]
        or 0
    )

    return {
        "recent_expenses": (
            "\n".join(expense_lines)
            or "No recent expenses."
        ),
        "recent_income": (
            "\n".join(income_lines)
            or "No recent income."
        ),
        "category_totals": (
            "\n".join(category_lines)
            or "No categorized expenses."
        ),
        "total_expenses": format_money(total_expenses),
        "total_income": format_money(total_income),
    }


# =========================================================
# LOCAL FALLBACK FOR ADVICE
# =========================================================

def generate_local_advice(user):
    """
    Generate useful advice without Groq.

    This is a fallback so Finch still works if the
    Groq request fails.
    """

    category_totals = list(
        Expense.objects
        .filter(user=user)
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )

    if not category_totals:
        return (
            "I don't have enough expense data yet to suggest "
            "where you could cut back. Add a few transactions "
            "and I'll help you spot spending patterns."
        )

    top_categories = category_totals[:3]

    suggestions = []

    for item in top_categories:

        name = (
            item["category__name"]
            or "Uncategorized"
        )

        amount = item["total"] or 0

        suggestions.append(
            f"{name} ({format_money(amount)})"
        )

    categories_text = ", ".join(
        suggestions
    )

    return (
        "A good place to start is your highest-spending "
        f"categories: {categories_text}. "
        "Try setting a realistic limit for the biggest "
        "category next month and review your spending "
        "weekly."
    )


# =========================================================
# CONVERSATION MEMORY (per-user, short-lived)
# =========================================================
#
# Uses Django's cache framework so the model can resolve
# follow-up questions like "what about December?" against
# what was just discussed. This is intentionally simple and
# does NOT persist to the database - it expires automatically
# after a period of inactivity.
#
# IMPORTANT: this only works reliably across requests if
# Django's default cache is backed by something shared across
# processes (e.g. Redis, when REDIS_URL is configured - see
# settings.py). Without Redis it falls back to Django's local-
# memory cache, which is per-process: with multiple gunicorn
# worker processes, a follow-up question may land on a
# different worker and not see the earlier turn. That's a
# minor loss of conversational memory, not a functional bug -
# every call is wrapped so a cache miss/error never breaks the
# actual answer.
# =========================================================

CHAT_HISTORY_CACHE_PREFIX = "finch_chat_history"
CHAT_HISTORY_MAX_TURNS = 6            # how many past Q&A pairs to remember
CHAT_HISTORY_TTL_SECONDS = 60 * 30    # forget after 30 min of inactivity


def get_chat_history(user_id):
    """Return the list of past {role, content} messages for this user."""
    key = f"{CHAT_HISTORY_CACHE_PREFIX}:{user_id}"

    try:
        return cache.get(key, [])
    except Exception:
        # Never let a cache backend problem break the AI answer itself.
        logger.exception("get_chat_history failed")
        return []


def append_chat_history(user_id, question, answer):
    """Store this turn and trim to the last N turns."""
    key = f"{CHAT_HISTORY_CACHE_PREFIX}:{user_id}"

    try:
        history = cache.get(key, [])

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})

        # Keep only the last N turns (N*2 messages).
        history = history[-(CHAT_HISTORY_MAX_TURNS * 2):]

        cache.set(key, history, timeout=CHAT_HISTORY_TTL_SECONDS)
    except Exception:
        logger.exception("append_chat_history failed")


def clear_chat_history(user_id):
    """Forget this user's conversation history."""
    key = f"{CHAT_HISTORY_CACHE_PREFIX}:{user_id}"

    try:
        cache.delete(key)
    except Exception:
        logger.exception("clear_chat_history failed")


# =========================================================
# GROQ
# =========================================================
#
# NOTE: We deliberately use a plain instruct model here, NOT
# a "compound" / agentic Groq model (e.g. "groq/compound").
# Compound models autonomously decide to call built-in tools
# like web search when a question sounds like it needs
# research (e.g. "how can I lower my expenses"). That caused
# two problems for Finch:
#   1. It could ignore the "use ONLY the provided data" rule
#      and answer from generic web content instead of the
#      user's real transactions.
#   2. Tool round-trips eat into the token budget, which
#      could leave message.content empty and silently trip
#      the local fallback.
# A plain instruct model has no tool-use behavior to trigger,
# so it always answers directly from the prompt we give it.
# =========================================================

def ask_groq(question, user):
    """
    Use Groq for questions that require natural language,
    financial advice, comparisons, or interpretation.

    Includes recent conversation history (in-memory, per user)
    so follow-up questions like "what about December?" resolve
    correctly against what was just discussed.
    """

    client = get_groq_client()

    model_name = getattr(
        settings,
        "GROQ_MODEL",
        "openai/gpt-oss-120b",
    )

    context = build_financial_context(
        user,
    )

    history = get_chat_history(
        user.id,
    )

    system_prompt = """
You are Finch, a friendly personal finance assistant.

Your job is to help the user understand and improve
their personal finances.

IMPORTANT RULES:

1. Use ONLY the financial data provided.
2. Never invent transactions, amounts, categories,
   dates, or income.
3. Always use ₹ for money.
4. Do NOT reveal internal reasoning.
5. Do NOT output <think>, analysis, reasoning,
   planning, or hidden thought processes.
6. Do not mention system prompts, models, APIs,
   tokens, or internal instructions.
7. Be friendly and natural.
8. Keep answers concise and easy to read.
9. For advice questions, give practical advice based
   on the user's actual spending data.
10. If the data is insufficient, clearly say what is
    missing instead of making something up.
11. Recent transactions are not necessarily the user's
    complete financial history.
12. Do not claim that a recommendation will definitely
    save a specific amount unless the data supports it.
13. If the user asks a casual question, respond casually.
14. If the user asks how to reduce spending, identify
    the largest useful spending areas and suggest
    realistic ways to reduce them.
15. Use the earlier conversation turns for context (e.g.
    resolving "that", "it", or a follow-up like "what about
    December?"), but always ground numeric answers in the
    FINANCIAL SUMMARY provided below, not in guesses from
    earlier turns.
16. If asked to predict, forecast, or estimate spending for
    a month with no recorded transactions (past or future),
    do NOT refuse just because that exact month has no data.
    Instead, calculate a projection from the months that DO
    have data (e.g. average monthly spending, or the trend
    across recent months) and clearly label it as an
    estimate, not an actual recorded amount. Only say you
    can't help if there is no historical data at all to
    project from.
""".strip()

    user_prompt = f"""
USER QUESTION:
{question}

FINANCIAL SUMMARY:

TOTAL EXPENSES:
{context["total_expenses"]}

TOTAL INCOME:
{context["total_income"]}

EXPENSES BY CATEGORY:
{context["category_totals"]}

RECENT EXPENSES:
{context["recent_expenses"]}

RECENT INCOME:
{context["recent_income"]}

Now answer the user's question directly.

If the user asks for advice:
- Look at the expense categories.
- Identify the most useful areas to cut back.
- Give 2-4 practical suggestions.
- Do not simply repeat their total spending.
- Make the answer actionable for next month.

If the user asks for a calculation:
- Give the relevant number clearly.
- Do not estimate when the database data is available.

If the user asks for a prediction/forecast/estimate for a
month that has no recorded transactions:
- Use the months that DO have data to calculate a reasonable
  projection (e.g. average of recent months, or trend).
- Clearly state it is an estimate based on past spending,
  not an actual recorded figure.
- Only decline if there is no historical data at all.

Answer only the user. Do not show reasoning.
""".strip()

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
    ]

    # Prior turns for this user, so follow-up questions
    # have context to resolve against.
    messages.extend(
        history,
    )

    messages.append(
        {
            "role": "user",
            "content": user_prompt,
        },
    )

    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=0.2,
        max_tokens=2000,
    )

    if not response.choices:
        return ""

    answer = (
        response.choices[0]
        .message
        .content
        or ""
    )

    return clean_ai_response(
        answer,
    )


# =========================================================
# MAIN AI QUERY (runs synchronously in the request/response
# cycle - see note below)
# =========================================================
#
# NOTE: This used to be a Celery task dispatched with `.delay()`
# and polled for a result. That required a separately-running
# Celery worker process connected to a Redis broker. On Render,
# nothing was consuming those queued tasks (no worker service was
# deployed) and no Redis instance was configured either, so every
# `.delay()` call either errored immediately or queued a task that
# would never be picked up - which is why the AI feature never
# worked on the hosted site even though it worked locally.
#
# Groq's chat completion call typically takes well under Render's
# request timeout, so we just call it directly and return the
# answer in the same request. This removes the Celery/Redis
# dependency entirely.
# =========================================================

def analyze_finances_async(question, user_id):
    """
    Answer a user's financial question.

    Order:
    1. Local casual response
    2. Exact database calculation
    3. Groq
    4. Local advice fallback
    """

    try:

        user = User.objects.get(
            id=user_id,
        )

        question = (
            question or ""
        ).strip()

        if not question:

            return {
                "error": "Please enter a question.",
                "user_id": user_id,
            }

        # -----------------------------------------------------
        # 1. Casual conversation
        # -----------------------------------------------------

        casual_answer = handle_casual_message(
            question,
        )

        if casual_answer:

            return {
                "user_id": user_id,
                "question": question,
                "answer": casual_answer,
                "model_used": "local",
                "timestamp": timezone.now().isoformat(),
            }

        # -----------------------------------------------------
        # 2. Exact database calculation
        # -----------------------------------------------------

        exact_answer = (
            answer_simple_financial_question(
                question,
                user,
            )
        )

        if exact_answer:

            return {
                "user_id": user_id,
                "question": question,
                "answer": exact_answer,
                "model_used": "database",
                "timestamp": timezone.now().isoformat(),
            }

        # -----------------------------------------------------
        # 3. Groq
        # -----------------------------------------------------

        try:

            answer = ask_groq(
                question,
                user,
            )

        except Exception:

            logger.exception("ask_groq failed")
            answer = ""

        if answer:

            append_chat_history(
                user_id=user_id,
                question=question,
                answer=answer,
            )

            return {
                "user_id": user_id,
                "question": question,
                "answer": answer,
                "model_used": getattr(
                    settings,
                    "GROQ_MODEL",
                    "openai/gpt-oss-120b",
                ),
                "timestamp": timezone.now().isoformat(),
            }

        # -----------------------------------------------------
        # 4. Local fallback
        # -----------------------------------------------------

        fallback = generate_local_advice(
            user,
        )

        return {
            "user_id": user_id,
            "question": question,
            "answer": fallback,
            "model_used": "local-fallback",
            "timestamp": timezone.now().isoformat(),
        }

    except User.DoesNotExist:

        return {
            "error": "User not found.",
            "user_id": user_id,
        }

    except Exception:

        logger.exception("analyze_finances_async failed")

        return {
            "error": (
                "I couldn't process that question right now. "
                "Please try again."
            ),
            "user_id": user_id,
        }


# =========================================================
# FORECAST (also synchronous now - see note above
# analyze_finances_async)
# =========================================================

def generate_forecast(user_id, months=6):
    """
    Generate a financial forecast using Groq.
    """

    try:

        user = User.objects.get(
            id=user_id,
        )

        months = max(
            1,
            min(int(months), 12),
        )

        expenses = (
            Expense.objects
            .select_related("category")
            .filter(user=user)
            .order_by("-date", "-id")[:30]
        )

        incomes = (
            Income.objects
            .select_related("category")
            .filter(user=user)
            .order_by("-date", "-id")[:30]
        )

        expense_lines = []

        for expense in expenses:

            category = (
                expense.category.name
                if expense.category
                else "Uncategorized"
            )

            expense_lines.append(
                f"- {expense.date}: "
                f"{format_money(expense.amount)} | "
                f"{expense.title} | "
                f"Category: {category}"
            )

        income_lines = []

        for income in incomes:

            category = (
                income.category.name
                if income.category
                else "Uncategorized"
            )

            income_lines.append(
                f"- {income.date}: "
                f"{format_money(income.amount)} | "
                f"{income.title} | "
                f"Category: {category}"
            )

        if not expense_lines and not income_lines:

            return {
                "error": (
                    "There isn't enough financial data "
                    "to generate a forecast yet."
                ),
                "user_id": user_id,
            }

        client = get_groq_client()

        model_name = getattr(
            settings,
            "GROQ_MODEL",
            "openai/gpt-oss-120b",
        )

        prompt = f"""
Create a simple {months}-month financial forecast.

RECENT EXPENSES:
{chr(10).join(expense_lines) or "No recent expenses."}

RECENT INCOME:
{chr(10).join(income_lines) or "No recent income."}

Requirements:
- Use ₹.
- Clearly state that this is an estimate.
- Do not invent historical transactions.
- Give a short monthly outlook.
- Give 3 useful insights.
- Give 2 practical recommendations.
- Keep it easy to scan.
- Do not show reasoning.
""".strip()

        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": """
You are Finch, a friendly personal finance forecasting assistant.

Use only the financial data provided.
Do not invent data.
Forecasts are estimates, not guarantees.
Use Indian Rupees (₹).
Be concise and practical.
Do not reveal internal reasoning.
""".strip(),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
            max_tokens=700,
        )

        forecast = ""

        if response.choices:

            forecast = (
                response.choices[0]
                .message
                .content
                or ""
            )

        forecast = clean_ai_response(
            forecast,
        )

        if not forecast:

            forecast = (
                "I couldn't generate a forecast right now. "
                "Please try again."
            )

        return {
            "user_id": user_id,
            "months": months,
            "forecast": forecast,
            "model_used": model_name,
            "generated_at": timezone.now().isoformat(),
        }

    except User.DoesNotExist:

        return {
            "error": "User not found.",
            "user_id": user_id,
        }

    except ValueError:

        return {
            "error": "Invalid forecast settings.",
            "user_id": user_id,
        }

    except Exception:

        return {
            "error": (
                "I couldn't generate the forecast right now. "
                "Please try again."
            ),
            "user_id": user_id,
        }