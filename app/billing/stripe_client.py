"""Stripe SDK wrappers for IntelliForge billing."""
import stripe
from flask import current_app


def get_stripe():
    """Return configured Stripe module."""
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    return stripe


def create_customer(email: str, name: str = None) -> dict:
    """Create a Stripe Customer record."""
    s = get_stripe()
    return s.Customer.create(email=email, name=name or email)


def create_checkout_session(customer_id: str, price_id: str, success_url: str, cancel_url: str) -> dict:
    """Create a Stripe Checkout Session for subscription."""
    s = get_stripe()
    return s.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
        subscription_data={
            "metadata": {"app": "intelliforgesystems"},
        },
    )


def cancel_subscription_at_period_end(subscription_id: str) -> dict:
    """Cancel a Stripe Subscription at period end (graceful downgrade)."""
    s = get_stripe()
    return s.Subscription.modify(
        subscription_id,
        cancel_at_period_end=True,
    )


def create_customer_portal_session(customer_id: str, return_url: str) -> dict:
    """Create a Stripe Billing Portal session for invoice/method management."""
    s = get_stripe()
    return s.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )


def retrieve_subscription(subscription_id: str) -> dict:
    """Fetch a subscription object from Stripe."""
    s = get_stripe()
    return s.Subscription.retrieve(subscription_id)


def construct_event(payload: bytes, sig_header: str, secret: str):
    """Verify and construct a Stripe webhook event."""
    s = get_stripe()
    return s.Webhook.construct_event(payload, sig_header, secret)
