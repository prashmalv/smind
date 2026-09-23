"""Vertical-specific demo catalogues, stores and customer language."""

from __future__ import annotations

# (sku, name, category, price, cost, is_combo)
QSR_MENU = [
    ("B01", "Chicken Burger", "Burgers", 179, 71, False),
    ("B02", "Veg Burger", "Burgers", 129, 48, False),
    ("B03", "Paneer Burger", "Burgers", 159, 66, False),
    ("B04", "Double Chicken Burger", "Burgers", 249, 108, False),
    ("W01", "Chicken Wrap", "Wraps", 149, 57, False),
    ("W02", "Veg Wrap", "Wraps", 119, 44, False),
    ("W03", "Spicy Chicken Wrap", "Wraps", 169, 66, False),
    ("S01", "French Fries (Regular)", "Sides", 89, 24, False),
    ("S02", "French Fries (Large)", "Sides", 129, 35, False),
    ("S03", "Peri Peri Fries", "Sides", 109, 31, False),
    ("S04", "Chicken Nuggets 6pc", "Sides", 139, 52, False),
    ("D01", "Cola 400ml", "Beverages", 69, 15, False),
    ("D02", "Iced Tea", "Beverages", 89, 22, False),
    ("D03", "Cold Coffee", "Beverages", 129, 38, False),
    ("D04", "Masala Lemonade", "Beverages", 79, 18, False),
    ("T01", "Chocolate Sundae", "Desserts", 99, 29, False),
    ("T02", "Brownie", "Desserts", 119, 38, False),
    ("C01", "Burger + Fries Combo", "Combos", 239, 92, True),
    ("C02", "Wrap + Drink Combo", "Combos", 199, 74, True),
    ("C03", "Family Feast", "Combos", 749, 312, True),
    ("V01", "Value Meal 149", "Value", 149, 66, True),
]

RETAIL_CATALOGUE = [
    ("G01", "Atta 5kg", "Staples", 289, 236, False),
    ("G02", "Basmati Rice 5kg", "Staples", 649, 520, False),
    ("G03", "Refined Oil 1L", "Staples", 159, 134, False),
    ("G04", "Toor Dal 1kg", "Staples", 179, 148, False),
    ("P01", "Shampoo 340ml", "Personal care", 349, 218, False),
    ("P02", "Body Wash 250ml", "Personal care", 279, 168, False),
    ("P03", "Toothpaste 150g", "Personal care", 119, 74, False),
    ("H01", "Detergent 2kg", "Home care", 399, 284, False),
    ("H02", "Floor Cleaner 1L", "Home care", 189, 121, False),
    ("S05", "Potato Chips 150g", "Snacks", 99, 58, False),
    ("S06", "Chocolate Bar", "Snacks", 89, 49, False),
    ("S07", "Biscuits Family Pack", "Snacks", 129, 78, False),
    ("D05", "Milk 1L", "Dairy", 68, 58, False),
    ("D06", "Curd 400g", "Dairy", 55, 42, False),
    ("D07", "Paneer 200g", "Dairy", 99, 72, False),
    ("F01", "Fresh Apples 1kg", "Fresh", 189, 142, False),
    ("F02", "Bananas 1dz", "Fresh", 69, 46, False),
    ("B05", "Bread Loaf", "Bakery", 49, 31, False),
    ("C04", "Monthly Essentials Pack", "Bundles", 1499, 1180, True),
    ("C05", "Breakfast Bundle", "Bundles", 349, 264, True),
]

STORES = [
    ("KOR", "Koramangala", "Bengaluru", "Karnataka", "South", "high-street"),
    ("IND", "Indiranagar", "Bengaluru", "Karnataka", "South", "high-street"),
    ("WFD", "Whitefield Mall", "Bengaluru", "Karnataka", "South", "mall"),
    ("HSR", "HSR Layout", "Bengaluru", "Karnataka", "South", "standalone"),
    ("BKC", "Bandra Kurla", "Mumbai", "Maharashtra", "West", "mall"),
    ("AND", "Andheri West", "Mumbai", "Maharashtra", "West", "high-street"),
    ("POW", "Powai", "Mumbai", "Maharashtra", "West", "standalone"),
    ("CP", "Connaught Place", "Delhi", "Delhi", "North", "high-street"),
    ("GUR", "Gurgaon Cyber Hub", "Gurugram", "Haryana", "North", "food-court"),
    ("NOI", "Noida Sector 18", "Noida", "Uttar Pradesh", "North", "mall"),
    ("HYD", "Hitec City", "Hyderabad", "Telangana", "South", "standalone"),
    ("CHN", "Anna Nagar", "Chennai", "Tamil Nadu", "South", "high-street"),
]

# Feedback templates. Each carries a theme the enrichment layer will recognise, so the
# voice-of-customer module has something true to group on rather than noise.
POSITIVE_FEEDBACK = [
    "Food was fresh and the staff were really friendly, quick service too.",
    "Great value for money, the combo is worth it.",
    "Delivery was fast and everything arrived hot. Very happy.",
    "The new item is delicious, definitely my favourite now.",
    "Clean store, polite staff, and the order was perfect.",
    "Quick counter, no waiting at all today. Excellent.",
    "Tasty food and generous portion. Will order again.",
    "Best in the area, consistent quality every time.",
]
NEGATIVE_FEEDBACK = [
    "Delivery was very late, food arrived cold after almost an hour.",
    "Waited in the queue for twenty minutes, far too slow at the counter.",
    "Portion size has become small for the price, feels overpriced now.",
    "Order was wrong, missing an item completely.",
    "The food was cold and bland, disappointed with the quality.",
    "Very expensive compared to what you get, poor value.",
    "Staff were rude and the store was dirty.",
    "App checkout kept failing, payment failed three times.",
    "Item was out of stock again, this keeps happening.",
    "Delivery delayed and the packaging leaked everywhere.",
]
NEUTRAL_FEEDBACK = [
    "Food was okay, nothing special.",
    "Average experience, about what I expected.",
    "Standard quality, the usual.",
]
# Planted, deliberately: a rising preference that is not yet on the menu.
TREND_FEEDBACK = [
    "Please bring back the spicy chicken option, it was the best.",
    "Would love to see more spicy items on the menu.",
    "The spicy chicken wrap is amazing, want more spicy choices.",
    "Need a spicy vegetarian option, everything is too mild.",
    "More spicy variants please, the current range is bland.",
]

COMPETITORS = [
    ("Burger Junction", 169.0),
    ("QuickBite", 139.0),
    ("Grill House", 199.0),
]
COMPETITOR_SIGNALS = [
    ("review", "Their spicy range is excellent and the portions are generous."),
    ("review", "Fast service, always fresh, and the value meals are worth it."),
    ("offer", "Launched a buy-one-get-one on all wraps this weekend."),
    ("price", "Dropped the combo price to compete on the value segment."),
    ("review", "Delivery was quick and the packaging was good."),
    ("menu", "Added three new spicy items to the permanent menu."),
    ("review", "Slightly expensive but the quality justifies it."),
    ("offer", "Running a 25% student discount across all outlets."),
]

# Specific pairings, planted so basket analysis has something true to find. A uniformly
# random add-on gives every pair a lift of about 1.0 — mathematically correct and
# useless, because "no pair is special" is what the data would then actually say.
QSR_PAIRS = {
    "Chicken Burger": "French Fries (Regular)",
    "Double Chicken Burger": "French Fries (Large)",
    "Veg Burger": "Cola 400ml",
    "Paneer Burger": "Masala Lemonade",
    "Chicken Wrap": "Peri Peri Fries",
    "Spicy Chicken Wrap": "Iced Tea",
    "Veg Wrap": "Chocolate Sundae",
}

RETAIL_PAIRS = {
    "Atta 5kg": "Refined Oil 1L",
    "Basmati Rice 5kg": "Toor Dal 1kg",
    "Milk 1L": "Bread Loaf",
    "Curd 400g": "Paneer 200g",
    "Detergent 2kg": "Floor Cleaner 1L",
    "Shampoo 340ml": "Body Wash 250ml",
}
