import os
import stripe
from dotenv import load_dotenv

# Load env from project root
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=env_path, encoding="utf-8-sig")

SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
if not SECRET_KEY:
    print("ERROR: STRIPE_SECRET_KEY not found in .env")
    exit(1)

stripe.api_key = SECRET_KEY


def create_or_get_price(product_name: str, unit_amount_cents: int, interval: str):
    """Create a product + price, or return existing if names match."""
    # Search existing products by name (naive; Stripe list is paginated)
    products = stripe.Product.list(limit=100)
    product = None
    for p in products.auto_paging_iter():
        if p.name == product_name:
            product = p
            break

    if not product:
        product = stripe.Product.create(name=product_name)
        print(f"  Created product: {product.name} ({product.id})")
    else:
        print(f"  Found existing product: {product.name} ({product.id})")

    # Check for existing price with same amount & interval
    prices = stripe.Price.list(product=product.id, limit=100)
    for pr in prices.auto_paging_iter():
        if (
            pr.unit_amount == unit_amount_cents
            and pr.currency == "usd"
            and pr.get("recurring", {}).get("interval") == interval
        ):
            print(f"  Found existing price: {pr.id} ({interval} ${unit_amount_cents/100:.0f})")
            return pr.id

    price = stripe.Price.create(
        product=product.id,
        unit_amount=unit_amount_cents,
        currency="usd",
        recurring={"interval": interval},
    )
    print(f"  Created price: {price.id} ({interval} ${unit_amount_cents/100:.0f})")
    return price.id


def main():
    print("Setting up Stripe Products & Prices for IntelliForge...\n")

    starter_monthly = create_or_get_price("IntelliForge Starter", 900, "month")
    starter_yearly = create_or_get_price("IntelliForge Starter", 8100, "year")
    pro_monthly = create_or_get_price("IntelliForge Pro", 2900, "month")
    pro_yearly = create_or_get_price("IntelliForge Pro", 26100, "year")

    print("\n--- DONE ---")
    print("Add these to your .env file:\n")
    print(f'STRIPE_PRICE_STARTER_MONTHLY={starter_monthly}')
    print(f'STRIPE_PRICE_STARTER_YEARLY={starter_yearly}')
    print(f'STRIPE_PRICE_PRO_MONTHLY={pro_monthly}')
    print(f'STRIPE_PRICE_PRO_YEARLY={pro_yearly}')


if __name__ == "__main__":
    main()
