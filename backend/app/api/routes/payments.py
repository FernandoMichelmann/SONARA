from datetime import datetime, timedelta, timezone
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models import PaymentOrder, User

router = APIRouter(prefix="/payments", tags=["Pagamentos"])
logger = logging.getLogger("sonara.payments")

LIFETIME_PRICE_CENTS = 4990
INFINITEPAY_BASE_URL = "https://api.checkout.infinitepay.io"


class PaymentConfirmation(BaseModel):
    order_nsu: str = Field(min_length=8, max_length=100)
    transaction_nsu: str = Field(min_length=5, max_length=160)
    slug: str = Field(min_length=2, max_length=160)


def _require_customer(user: User) -> None:
    if user.role != "user":
        raise HTTPException(status_code=403, detail="Recurso disponível apenas para contas de clientes.")


def _infinitepay_post(endpoint: str, payload: dict) -> dict:
    api_key = (settings.infinitepay_api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="A integração InfinitePay ainda não foi configurada no servidor.")
    request = Request(
        INFINITEPAY_BASE_URL + endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Api-Key": api_key},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Resposta inválida da InfinitePay.")
            return data
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        logger.error("InfinitePay HTTP %s: %s", error.code, detail)
        raise HTTPException(status_code=502, detail="A InfinitePay não conseguiu processar a solicitação. Verifique a configuração e tente novamente.")
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        logger.exception("Falha na comunicação com a InfinitePay: %s", error)
        raise HTTPException(status_code=502, detail="Não foi possível comunicar com a InfinitePay. Tente novamente.")


def _confirm_order(db: Session, order: PaymentOrder, transaction_nsu: str, slug: str) -> bool:
    if order.status == "paid":
        return True
    handle = (settings.infinitepay_handle or "").strip().lstrip("$")
    if not handle:
        raise HTTPException(status_code=503, detail="A InfiniteTag da InfinitePay não está configurada no servidor.")

    result = _infinitepay_post("/payment_check", {
        "handle": handle,
        "order_nsu": order.order_nsu,
        "transaction_nsu": transaction_nsu,
        "slug": slug,
    })
    order.transaction_nsu = transaction_nsu
    order.invoice_slug = slug
    if not result.get("success"):
        db.commit()
        return False
    if not result.get("paid"):
        db.commit()
        return False

    try:
        paid_amount = int(result.get("amount", 0))
        received_amount = int(result.get("paid_amount", 0))
    except (TypeError, ValueError):
        order.status = "review"
        db.commit()
        return False

    if paid_amount != order.amount_cents or received_amount < paid_amount:
        order.status = "review"
        db.commit()
        logger.error("Valor divergente no pedido %s: amount=%s paid_amount=%s", order.order_nsu, paid_amount, received_amount)
        return False

    order.status = "paid"
    order.paid_amount_cents = received_amount
    order.capture_method = str(result.get("capture_method") or "")[:30] or None
    order.installments = int(result.get("installments") or 1)
    order.paid_at = datetime.now(timezone.utc)
    user = db.get(User, order.user_id)
    if not user or not user.is_active:
        order.status = "review"
        db.commit()
        return False
    user.lifetime_access = True
    user.lifetime_access_at = order.paid_at
    db.commit()
    return True


@router.post("/checkout")
def create_lifetime_checkout(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_customer(user)
    if user.lifetime_access:
        return {"already_active": True, "message": "Sua conta já possui acesso vitalício."}
    if not settings.infinitepay_api_key or not settings.infinitepay_handle:
        raise HTTPException(status_code=503, detail="Configure INFINITEPAY_API_KEY e INFINITEPAY_HANDLE no backend/.env.")

    now = datetime.now(timezone.utc)
    previous = db.scalar(
        select(PaymentOrder)
        .where(
            PaymentOrder.user_id == user.id,
            PaymentOrder.status == "pending",
            PaymentOrder.checkout_url.is_not(None),
            PaymentOrder.created_at >= now - timedelta(hours=47),
        )
        .order_by(PaymentOrder.created_at.desc())
    )
    if previous:
        return {"checkout_url": previous.checkout_url, "order_nsu": previous.order_nsu, "reused": True}

    order_nsu = f"sonara-{user.id}-{uuid4().hex}"
    valid_until = (now + timedelta(hours=48)).isoformat()
    payload = {
        "order_nsu": order_nsu,
        "redirect_url": settings.frontend_base_url.rstrip("/") + "/?payment_return=1",
        "items": [{
            "quantity": 1,
            "price": LIFETIME_PRICE_CENTS,
            "description": "SONARA Vitalício - acesso único",
        }],
        "customer": {"name": user.full_name, "email": user.email},
        "options": {
            "single_payment": True,
            "valid_until": valid_until,
            "payment_methods_enabled": ["credit_card", "pix"],
        },
    }
    webhook_url = (settings.infinitepay_webhook_url or "").strip()
    if webhook_url:
        if not webhook_url.startswith("https://"):
            raise HTTPException(status_code=503, detail="INFINITEPAY_WEBHOOK_URL precisa ser uma URL pública HTTPS.")
        payload["webhook_url"] = webhook_url

    order = PaymentOrder(
        user_id=user.id,
        order_nsu=order_nsu,
        amount_cents=LIFETIME_PRICE_CENTS,
        status="creating",
    )
    db.add(order)
    db.commit()
    try:
        response = _infinitepay_post("/links", payload)
        checkout_url = response.get("url") or response.get("checkout_url") or response.get("link")
        if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
            logger.error("Resposta de criação de checkout sem URL reconhecida: %s", response)
            order.status = "error"
            db.commit()
            raise HTTPException(status_code=502, detail="A InfinitePay não retornou um link de pagamento válido.")
        order.checkout_url = checkout_url
        order.status = "pending"
        db.commit()
        return {"checkout_url": checkout_url, "order_nsu": order_nsu}
    except Exception:
        if order.status == "creating":
            order.status = "error"
            db.commit()
        raise


@router.post("/confirm")
def confirm_lifetime_payment(
    payload: PaymentConfirmation,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_customer(user)
    order = db.scalar(select(PaymentOrder).where(
        PaymentOrder.order_nsu == payload.order_nsu,
        PaymentOrder.user_id == user.id,
    ))
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado para esta conta.")
    paid = _confirm_order(db, order, payload.transaction_nsu, payload.slug)
    db.refresh(user)
    return {
        "paid": paid,
        "status": order.status,
        "has_lifetime_access": user.lifetime_access,
        "message": "Pagamento confirmado. Seu acesso vitalício está ativo." if paid else "Ainda não foi possível confirmar o pagamento. Aguarde alguns instantes e tente novamente.",
    }


@router.post("/webhook/infinitepay")
def infinitepay_webhook(payload: dict, db: Session = Depends(get_db)):
    order_nsu = str(payload.get("order_nsu") or "").strip()
    transaction_nsu = str(payload.get("transaction_nsu") or "").strip()
    slug = str(payload.get("invoice_slug") or payload.get("slug") or "").strip()
    if not order_nsu or not transaction_nsu or not slug:
        raise HTTPException(status_code=400, detail="Dados insuficientes para validar a notificação.")
    order = db.scalar(select(PaymentOrder).where(PaymentOrder.order_nsu == order_nsu))
    if not order:
        raise HTTPException(status_code=400, detail="Pedido não reconhecido.")
    _confirm_order(db, order, transaction_nsu, slug)
    return {"received": True}
