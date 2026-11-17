#!/usr/bin/env python3
"""Rebrand Stripe products — standalone version."""
import os
import sys

# Read .env manually
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
with open(env_path, encoding="utf-8-sig") as f:
    for line in f:
        if line.startswith("STRIPE_SECRET_KEY="):
            os.environ["STRIPE_SECRET_KEY"] = line.strip().split("=", 1)[1]
            break

import stripe

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
if not stripe.api_key:
    print("ERROR: STRIPE_SECRET_KEY not found")
    sys.exit(1)

print(f"Using key: {stripe.api_key[:12]}...\n")

OLD_NAMES = ["MoM AI Starter", "MoM AI Pro"]
NEW_NAMES = {
    "MoM AI Starter": "IntelliForge Starter",
    "MoM AI Pro": "IntelliForge Pro",
}

products = stripe.Product.list(limit=100)
renamed = 0

for product in products.auto_paging_iter():
    old_name = product.name
    if old_name in OLD_NAMES:
        new_name = NEW_NAMES[old_name]
        print(f"Renaming: '{old_name}' -> '{new_name}'")
        stripe.Product.modify(product.id, name=new_name)
        renamed += 1
    elif "MoM" in old_name:
        print(f"Found (manual review): '{old_name}' (ID: {product.id})")

if renamed == 0:
    print("No old 'MoM AI' products found. Already rebranded or products use different names.")
else:
    print(f"\nRenamed {renamed} product(s).")

print("\nDone. Check: https://dashboard.stripe.com/products")
