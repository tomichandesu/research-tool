"""Stripe integration service for subscription management."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from functools import partial

import stripe

from ..config import settings
from ..database import async_session_factory
from ..models import User

logger = logging.getLogger(__name__)

# Configure stripe module
stripe.api_key = settings.STRIPE_SECRET_KEY

# Price ID -> (plan_type, plan_billing) mapping
PRICE_TO_PLAN: dict[str, tuple[str, str]] = {}

# Plan candidate limits
_PLAN_CANDIDATE_LIMITS = {
    "lite": 20,
    "standard": 40,
    "pro": 100,
}


def _build_price_map() -> None:
    """Build the price-to-plan mapping from config (called once at import)."""
    mapping = {
        settings.STRIPE_PRICE_LITE_ANNUAL: ("lite", "annual"),
        settings.STRIPE_PRICE_STANDARD_ANNUAL: ("standard", "annual"),
        settings.STRIPE_PRICE_PRO_ANNUAL: ("pro", "annual"),
    }
    for price_id, plan_info in mapping.items():
        if price_id:  # skip empty/unconfigured
            PRICE_TO_PLAN[price_id] = plan_info


_build_price_map()


async def _run_sync(func, *args, **kwargs):
    """Run a synchronous Stripe SDK call in an executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


async def get_or_create_customer(user: User) -> str:
    """Get existing Stripe customer or create a new one.

    Returns the Stripe customer ID and saves it to the user record.
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = await _run_sync(
        stripe.Customer.create,
        email=user.email,
        name=user.display_name,
        metadata={"user_id": str(user.id)},
    )
    customer_id = customer.id

    # Save to DB
    async with async_session_factory() as db:
        db_user = await db.get(User, user.id)
        if db_user:
            db_user.stripe_customer_id = customer_id
            await db.commit()

    return customer_id


async def create_checkout_session(
    user: User,
    price_id: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session and return the URL."""
    customer_id = await get_or_create_customer(user)

    session = await _run_sync(
        stripe.checkout.Session.create,
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": str(user.id)},
    )
    return session.url


async def create_portal_session(user: User, return_url: str) -> str:
    """Create a Stripe Customer Portal session and return the URL."""
    if not user.stripe_customer_id:
        raise ValueError("User has no Stripe customer ID")

    session = await _run_sync(
        stripe.billing_portal.Session.create,
        customer=user.stripe_customer_id,
        return_url=return_url,
    )
    return session.url


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify webhook signature and construct the event object."""
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )


async def sync_subscription_to_user(subscription: stripe.Subscription) -> None:
    """Sync a Stripe subscription state to the local User record."""
    customer_id = (
        subscription.customer
        if isinstance(subscription.customer, str)
        else subscription.customer.id
    )

    # Determine plan from the first line item's price
    plan_type = "lite"
    plan_billing = "none"
    candidate_limit = 20

    if subscription.get("items") and subscription["items"].get("data"):
        price_id = subscription["items"]["data"][0]["price"]["id"]
        if price_id in PRICE_TO_PLAN:
            plan_type, plan_billing = PRICE_TO_PLAN[price_id]
            candidate_limit = _PLAN_CANDIDATE_LIMITS.get(plan_type, 20)

    # Calculate expiry from current_period_end
    period_end = subscription.get("current_period_end")
    plan_expires_at = (
        datetime.utcfromtimestamp(period_end) + timedelta(days=1)
        if period_end
        else None
    )

    async with async_session_factory() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            logger.warning(
                f"Webhook: no user found for Stripe customer {customer_id}"
            )
            return

        user.stripe_subscription_id = subscription.id
        user.stripe_subscription_status = subscription.status
        user.service_type = "alumni"
        user.plan_type = plan_type
        user.plan_billing = plan_billing
        user.plan_expires_at = plan_expires_at
        user.candidate_limit_monthly = candidate_limit

        await db.commit()
        logger.info(
            f"Webhook: synced subscription {subscription.id} -> "
            f"user {user.id} ({user.email}): "
            f"plan={plan_type}/{plan_billing}, status={subscription.status}"
        )


async def handle_subscription_deleted(subscription: stripe.Subscription) -> None:
    """Handle subscription cancellation: downgrade to lite."""
    customer_id = (
        subscription.customer
        if isinstance(subscription.customer, str)
        else subscription.customer.id
    )

    async with async_session_factory() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            logger.warning(
                f"Webhook: no user found for Stripe customer {customer_id} (deleted)"
            )
            return

        user.stripe_subscription_id = None
        user.stripe_subscription_status = "canceled"
        user.plan_type = "lite"
        user.plan_billing = "none"
        user.plan_expires_at = None
        user.candidate_limit_monthly = 20

        await db.commit()
        logger.info(
            f"Webhook: subscription canceled for user {user.id} ({user.email}), "
            f"downgraded to lite"
        )
