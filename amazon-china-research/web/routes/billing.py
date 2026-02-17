"""Billing routes for Stripe subscription management."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user, require_login
from ..config import settings
from ..database import get_db
from ..models import User
from ..services.stripe_service import (
    construct_webhook_event,
    create_checkout_session,
    create_portal_session,
    handle_subscription_deleted,
    sync_subscription_to_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

# Plan -> Price ID mapping (annual only for alumni)
_PRICE_MAP = {
    ("lite", "annual"): settings.STRIPE_PRICE_LITE_ANNUAL,
    ("standard", "annual"): settings.STRIPE_PRICE_STANDARD_ANNUAL,
    ("pro", "annual"): settings.STRIPE_PRICE_PRO_ANNUAL,
}


@router.get("/checkout")
async def billing_checkout(
    request: Request,
    plan: str,
    billing: str,
    user: User = Depends(require_login),
):
    """Redirect to Stripe Checkout for subscription purchase."""
    price_id = _PRICE_MAP.get((plan, billing))
    if not price_id:
        return RedirectResponse(url="/?error=invalid_plan", status_code=303)

    base_url = str(request.base_url).rstrip("/")
    checkout_url = await create_checkout_session(
        user=user,
        price_id=price_id,
        success_url=f"{base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/",
    )
    return RedirectResponse(url=checkout_url, status_code=303)


@router.get("/success", response_class=HTMLResponse)
async def billing_success(
    request: Request,
    user: User = Depends(require_login),
):
    """Display payment success page."""
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "billing/success.html",
        {"request": request, "user": user},
    )


@router.get("/portal")
async def billing_portal(
    request: Request,
    user: User = Depends(require_login),
):
    """Redirect to Stripe Customer Portal for subscription management."""
    if not user.stripe_customer_id:
        return RedirectResponse(url="/?error=no_subscription", status_code=303)

    base_url = str(request.base_url).rstrip("/")
    portal_url = await create_portal_session(
        user=user,
        return_url=f"{base_url}/",
    )
    return RedirectResponse(url=portal_url, status_code=303)


@router.post("/webhook")
async def billing_webhook(request: Request):
    """Receive Stripe webhook events (no auth, signature-verified)."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except Exception as e:
        logger.warning(f"Webhook signature verification failed: {e}")
        return {"error": "Invalid signature"}, 400

    event_type = event.type
    logger.info(f"Webhook received: {event_type}")

    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        await sync_subscription_to_user(event.data.object)

    elif event_type == "customer.subscription.deleted":
        await handle_subscription_deleted(event.data.object)

    elif event_type == "checkout.session.completed":
        logger.info(f"Checkout completed: {event.data.object.id}")

    elif event_type == "invoice.payment_failed":
        logger.warning(
            f"Payment failed for customer {event.data.object.get('customer')}. "
            "Stripe will auto-retry."
        )

    return {"status": "ok"}
