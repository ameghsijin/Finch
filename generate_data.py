# generate_data.py
import os
import django
from datetime import datetime, timedelta
import random
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Finch.settings')
django.setup()

from django.contrib.auth.models import User
from app.models import Category, Expense, Income, Budget

def create_categories():
    """Create categories if they don't exist"""
    expense_categories = [
        {'name': 'Food', 'color': '#FF6B6B', 'icon': 'Food'},
        {'name': 'Transport', 'color': '#4ECDC4', 'icon': 'Transport'},
        {'name': 'Rent', 'color': '#45B7D1', 'icon': 'Home'},
        {'name': 'Utilities', 'color': '#96CEB4', 'icon': 'Home'},
        {'name': 'Entertainment', 'color': '#FFEAA7', 'icon': 'Tag'},
        {'name': 'Shopping', 'color': '#A29BFE', 'icon': 'Shopping'},
        {'name': 'Healthcare', 'color': '#FD79A8', 'icon': 'Tag'},
        {'name': 'Education', 'color': '#00CEC9', 'icon': 'Tag'},
        {'name': 'Savings', 'color': '#55EFC4', 'icon': 'Tag'},
        {'name': 'Personal Care', 'color': '#FDCB6E', 'icon': 'Tag'},
    ]
    
    income_categories = [
        {'name': 'Salary', 'color': '#55EFC4', 'icon': 'Salary'},
        {'name': 'Freelance', 'color': '#FDCB6E', 'icon': 'Salary'},
        {'name': 'Investment', 'color': '#00CEC9', 'icon': 'Salary'},
        {'name': 'Gifts', 'color': '#FF6B6B', 'icon': 'Salary'},
    ]
    
    created = 0
    for cat in expense_categories:
        obj, created_flag = Category.objects.get_or_create(
            name=cat['name'],
            defaults={'type': 'expense', 'color': cat['color'], 'icon': cat['icon']}
        )
        if created_flag:
            created += 1
    
    for cat in income_categories:
        obj, created_flag = Category.objects.get_or_create(
            name=cat['name'],
            defaults={'type': 'income', 'color': cat['color'], 'icon': cat['icon']}
        )
        if created_flag:
            created += 1
    
    print(f"✅ Created {created} new categories (existing ones skipped)")
    return True

def get_category(name):
    """Helper to get category by name"""
    return Category.objects.filter(name=name).first()

def generate_expenses(user, year=2026):
    """Generate expenses for June, July, August"""
    expenses_data = []
    
    # Food expenses (daily)
    food_items = [
        'Grocery Shopping', 'Restaurant Dinner', 'Lunch at Cafe', 
        'Breakfast', 'Snacks', 'Coffee Shop', 'Takeout Food',
        'Lunch at Office', 'Dinner with Friends', 'Bakery'
    ]
    
    # Transport expenses
    transport_items = [
        'Cab', 'Bus Ticket', 'Metro Pass', 'Fuel', 'Auto',
        'Flight Ticket', 'Train Ticket', 'Car Service'
    ]
    
    # Entertainment
    entertainment_items = [
        'Movie Tickets', 'Concert', 'Netflix Subscription', 
        'Amazon Prime', 'Gaming', 'Sports Event', 'Theatre Show'
    ]
    
    # Shopping
    shopping_items = [
        'Clothing', 'Shoes', 'Electronics', 'Books', 
        'Home Decor', 'Kitchen Items', 'Phone Accessories'
    ]
    
    # Healthcare
    healthcare_items = [
        'Medicine', 'Doctor Visit', 'Dental Checkup', 
        'Lab Tests', 'Health Checkup', 'Eye Checkup'
    ]
    
    # Utilities
    utility_items = [
        'Electricity Bill', 'Water Bill', 'Internet Bill', 
        'Gas Bill', 'Phone Bill', 'Maintenance Fee'
    ]
    
    # Personal Care
    personal_items = [
        'Haircut', 'Salon', 'Gym Membership', 
        'Skincare Products', 'Perfume', 'Toiletries'
    ]
    
    # Education
    education_items = [
        'Course Fee', 'Books', 'Online Course', 
        'Workshop', 'Tuition Fee'
    ]
    
    # Map categories to their items
    expense_mapping = {
        'Food': food_items,
        'Transport': transport_items,
        'Entertainment': entertainment_items,
        'Shopping': shopping_items,
        'Healthcare': healthcare_items,
        'Utilities': utility_items,
        'Personal Care': personal_items,
        'Education': education_items,
    }
    
    # Generate data for each month
    months = [6, 7, 8]  # June, July, August
    total_expenses = 0
    
    for month in months:
        # Number of days in month
        if month in [6, 7, 8]:
            days_in_month = 30  # All these months have 30 days
        
        # Generate expenses for each day (1-5 expenses per day)
        for day in range(1, days_in_month + 1):
            # Randomly decide if there are expenses (80% chance)
            if random.random() > 0.8:
                continue
            
            num_expenses = random.randint(1, 3)
            date = datetime(year, month, day).date()
            
            for _ in range(num_expenses):
                # Pick a random category and item
                category_name = random.choice(list(expense_mapping.keys()))
                category = get_category(category_name)
                if not category:
                    continue
                
                items = expense_mapping[category_name]
                title = random.choice(items)
                
                # Different amount ranges per category
                amount_ranges = {
                    'Food': (50, 1500),
                    'Transport': (50, 2000),
                    'Entertainment': (100, 1500),
                    'Shopping': (200, 3000),
                    'Healthcare': (200, 2000),
                    'Utilities': (500, 3000),
                    'Personal Care': (100, 1000),
                    'Education': (500, 5000),
                }
                
                min_amt, max_amt = amount_ranges.get(category_name, (50, 500))
                amount = random.randint(min_amt, max_amt)
                
                # Add some larger monthly expenses (rent, etc.)
                if category_name == 'Utilities' and day == 5:
                    amount = random.randint(800, 3000)
                
                payment_method = random.choice(['UPI', 'Cash', 'Card', 'Bank Transfer'])
                
                # Create expense
                expense = Expense.objects.create(
                    user=user,
                    title=title,
                    amount=Decimal(amount),
                    date=date,
                    payment_method=payment_method,
                    notes=f"Auto-generated expense for {date}",
                    category=category
                )
                total_expenses += amount
    
    print(f"✅ Created expenses totaling ₹{total_expenses:,.2f}")
    return total_expenses

def generate_incomes(user, year=2026):
    """Generate incomes for June, July, August"""
    total_incomes = 0
    
    # Monthly salary
    salary_amount = 50000
    for month in [6, 7, 8]:
        date = datetime(year, month, 1).date()
        category = get_category('Salary')
        if category:
            Income.objects.create(
                user=user,
                title='Monthly Salary',
                amount=Decimal(salary_amount),
                date=date,
                notes=f'{date.strftime("%B")} salary',
                category=category
            )
            total_incomes += salary_amount
    
    # Freelance income (random dates)
    freelance_category = get_category('Freelance')
    if freelance_category:
        freelance_amounts = [5000, 8000, 3000, 10000, 6000]
        for month in [6, 7, 8]:
            # 1-3 freelance payments per month
            num_payments = random.randint(1, 3)
            for _ in range(num_payments):
                day = random.randint(5, 28)
                date = datetime(year, month, day).date()
                amount = random.choice(freelance_amounts)
                Income.objects.create(
                    user=user,
                    title=f'Freelance Project {date.strftime("%b")}',
                    amount=Decimal(amount),
                    date=date,
                    notes=f'Freelance payment',
                    category=freelance_category
                )
                total_incomes += amount
    
    # Investment income (once per month)
    investment_category = get_category('Investment')
    if investment_category:
        for month in [6, 7, 8]:
            day = random.randint(10, 20)
            date = datetime(year, month, day).date()
            amount = random.randint(300, 1500)
            Income.objects.create(
                user=user,
                title='Investment Returns',
                amount=Decimal(amount),
                date=date,
                notes=f'Monthly investment return',
                category=investment_category
            )
            total_incomes += amount
    
    print(f"✅ Created incomes totaling ₹{total_incomes:,.2f}")
    return total_incomes

def create_budgets(user, year=2026):
    """Create budgets for categories"""
    budgets_created = 0
    
    # Budget amounts per category
    budget_data = {
        'Food': 10000,
        'Transport': 5000,
        'Utilities': 5000,
        'Entertainment': 3000,
        'Shopping': 4000,
        'Healthcare': 2000,
        'Personal Care': 1500,
        'Education': 3000,
    }
    
    for month in [6, 7, 8]:
        for category_name, amount in budget_data.items():
            category = get_category(category_name)
            if not category:
                continue
            
            # Create budget if doesn't exist
            obj, created = Budget.objects.get_or_create(
                user=user,
                category=category,
                period='monthly',
                month=month,
                year=year,
                defaults={
                    'amount': Decimal(amount),
                    'alert_threshold': 80
                }
            )
            if created:
                budgets_created += 1
    
    print(f"✅ Created {budgets_created} budgets")
    return budgets_created

def main():
    """Main function to generate all data"""
    print("🚀 Starting data generation...")
    
    # Get first user
    user = User.objects.first()
    if not user:
        print("❌ No user found! Please create a user first.")
        print("   Run: python manage.py createsuperuser")
        return
    
    print(f"📊 Generating data for user: {user.username}")
    
    # Create categories first
    create_categories()
    
    # Generate data
    total_expenses = generate_expenses(user)
    total_incomes = generate_incomes(user)
    create_budgets(user)
    
    print(f"\n🎉 Data generation complete!")
    print(f"   Total Expenses: ₹{total_expenses:,.2f}")
    print(f"   Total Incomes: ₹{total_incomes:,.2f}")
    print(f"   Net Savings: ₹{total_incomes - total_expenses:,.2f}")

if __name__ == '__main__':
    main()