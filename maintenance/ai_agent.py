import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from django.db.models import Q

from .models import Complaint, User, Vendor


logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_ROUNDS = 8
HISTORY_LIMIT = 24

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_my_profile",
            "description": "Who is signed in: name, role, pump, area.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pumps",
            "description": "List consumer pumps this user is allowed to see.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Optional name or pump code search"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_vendors",
            "description": "List vendors. Use before answering questions about a vendor's jobs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Optional vendor name search"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_complaints",
            "description": "Search complaints this user can see (pump, vendor, status, category).",
            "parameters": {
                "type": "object",
                "properties": {
                    "vendor": {"type": "string", "description": "Vendor name contains"},
                    "pump": {"type": "string", "description": "Pump name or code contains"},
                    "status": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["TANK", "DU", "CIVIL", "ELECTRICAL", "OTHER"],
                    },
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_complaint",
            "description": "Full detail for one complaint by CMP id, e.g. CMP-2026-001.",
            "parameters": {
                "type": "object",
                "properties": {"complaint_id": {"type": "string"}},
                "required": ["complaint_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lodge_complaint",
            "description": "Create a complaint ONLY after the user confirmed the summary. Set confirmed=true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {
                        "type": "boolean",
                        "description": "Must be true. User said yes to the summary.",
                    },
                    "pump_id": {
                        "type": "integer",
                        "description": "Required for officers. Customers use their mapped pump if omitted.",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["TANK", "DU", "CIVIL", "ELECTRICAL", "OTHER"],
                    },
                    "description": {"type": "string"},
                    "priority": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                    "du_make": {"type": "string"},
                    "du_model": {"type": "string"},
                    "du_serial": {"type": "string"},
                },
                "required": ["confirmed", "category", "description"],
            },
        },
    },
]


def _system_prompt(user: User) -> str:
    pump = user.consumer_pump.name if user.consumer_pump_id else "none"
    return f"""You are the PAHLE-APP assistant for IndianOil Army Consumer Pump maintenance.

Signed-in user: {user.get_full_name() or user.username}
Role: {user.get_role_display()} ({user.role})
Mapped pump: {pump}

You can look up real PAHLE data with tools and answer in plain language.
Only show complaints, pumps, and vendors the tools return — that is already scoped to this login.
Typical questions: complaints for a vendor, open tickets at a pump, status of CMP-…, aging, category mix.

To RAISE a complaint:
1. Ask one missing thing at a time.
2. Need: category (Tank Related, DU related, Civil Work, Electrical Work, Others), description, priority (Low / Medium / High).
3. If category is DU related, also ask Make, Model, Sr. No.
4. Customers use their mapped pump. Officers must pick a pump (use list_pumps).
5. Show a short summary and ask them to confirm.
6. Call lodge_complaint only after they clearly confirm. Set confirmed=true.
7. Never lodge without confirmation.

Vendors cannot lodge complaints; they can only ask about jobs assigned to them.
Be concise. If a tool returns no rows, say you found none in their access — do not invent tickets.
"""


def _compact_complaint(c: Complaint) -> dict:
    return {
        "complaint_id": c.complaint_id,
        "pump": c.pump.name,
        "pump_code": c.pump.pump_code,
        "category": c.get_category_display(),
        "status": c.get_status_display(),
        "priority": c.get_priority_display(),
        "vendor": c.assigned_vendor.name if c.assigned_vendor_id else None,
        "aging_days": c.aging_days,
        "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
        "description": (c.description or "")[:280],
        "du_make": c.du_make or None,
        "du_model": c.du_model or None,
        "du_serial": c.du_serial or None,
    }


def _dumps(data) -> str:
    return json.dumps(data, default=str, ensure_ascii=False)


def run_tool(user: User, name: str, arguments: dict, request) -> str:
    from .serializers import ComplaintSerializer
    from .views import scoped_complaints, scoped_pumps

    args = arguments or {}
    if name == "get_my_profile":
        return _dumps(
            {
                "name": user.get_full_name() or user.username,
                "role": user.role,
                "role_label": user.get_role_display(),
                "pump": user.consumer_pump.name if user.consumer_pump_id else None,
                "pump_id": user.consumer_pump_id,
                "sales_area": user.sales_area.name if user.sales_area_id else None,
            }
        )
    if name == "list_pumps":
        qs = scoped_pumps(user)
        q = (args.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(pump_code__icontains=q))
        rows = [
            {
                "id": p.id,
                "name": p.name,
                "pump_code": p.pump_code,
                "city": p.city,
                "sales_area": p.sales_area.code,
            }
            for p in qs.order_by("name")[:30]
        ]
        return _dumps({"count": len(rows), "pumps": rows})
    if name == "list_vendors":
        qs = Vendor.objects.filter(is_active=True)
        q = (args.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        rows = []
        for v in qs.order_by("name")[:30]:
            jobs = scoped_complaints(user).filter(assigned_vendor=v).exclude(status=Complaint.Status.CLOSED)
            rows.append(
                {
                    "id": v.id,
                    "name": v.name,
                    "specialization": v.get_specialization_display(),
                    "open_jobs_you_can_see": jobs.count(),
                }
            )
        return _dumps({"count": len(rows), "vendors": rows})
    if name == "list_complaints":
        qs = scoped_complaints(user)
        vendor = (args.get("vendor") or "").strip()
        pump = (args.get("pump") or "").strip()
        status = (args.get("status") or "").strip().upper()
        category = (args.get("category") or "").strip().upper()
        if vendor:
            qs = qs.filter(assigned_vendor__name__icontains=vendor)
        if pump:
            qs = qs.filter(Q(pump__name__icontains=pump) | Q(pump__pump_code__icontains=pump))
        if status:
            qs = qs.filter(status=status)
        if category:
            qs = qs.filter(category=category)
        try:
            limit = min(max(int(args.get("limit") or 12), 1), 25)
        except (TypeError, ValueError):
            limit = 12
        items = [_compact_complaint(c) for c in qs.order_by("-created_at")[:limit]]
        return _dumps({"count": len(items), "complaints": items})
    if name == "get_complaint":
        cid = (args.get("complaint_id") or "").strip()
        rec = scoped_complaints(user).filter(complaint_id__iexact=cid).first()
        if not rec:
            return _dumps({"error": "Complaint not found or you do not have access."})
        data = _compact_complaint(rec)
        data["officer"] = rec.sales_officer.get_full_name() if rec.sales_officer_id else None
        data["submitted_by"] = rec.submitted_by.get_full_name() if rec.submitted_by_id else None
        return _dumps(data)
    if name == "lodge_complaint":
        if user.role == User.Role.VENDOR:
            return _dumps({"error": "Vendors cannot lodge complaints."})
        if not args.get("confirmed"):
            return _dumps(
                {
                    "error": "Not lodged. Show a summary and wait for the user to confirm, then call again with confirmed=true."
                }
            )
        payload = {
            "category": (args.get("category") or "").upper(),
            "description": (args.get("description") or "").strip(),
            "priority": (args.get("priority") or "MEDIUM").upper(),
            "du_make": (args.get("du_make") or "").strip(),
            "du_model": (args.get("du_model") or "").strip(),
            "du_serial": (args.get("du_serial") or "").strip(),
        }
        pump_id = args.get("pump_id")
        if user.role == User.Role.CP_USER and user.consumer_pump_id:
            payload["pump"] = user.consumer_pump_id
        elif pump_id:
            if not scoped_pumps(user).filter(pk=pump_id).exists():
                return _dumps({"error": "Invalid pump for this user."})
            payload["pump"] = pump_id
        else:
            return _dumps({"error": "Select a consumer pump (pump_id)."})
        serializer = ComplaintSerializer(data=payload, context={"request": request})
        if not serializer.is_valid():
            return _dumps({"error": serializer.errors})
        complaint = serializer.save()
        from .notifications import notify_new_complaint

        notify_new_complaint(complaint)
        return _dumps(
            {
                "ok": True,
                "complaint_id": complaint.complaint_id,
                "status": complaint.get_status_display(),
                "pump": complaint.pump.name,
            }
        )
    return _dumps({"error": f"Unknown tool {name}"})


def _groq_chat(body: dict) -> dict:
    api_key = getattr(settings, "GROQ_API_KEY", "") or ""
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PAHLE-APP/1.0",
        },
        method="POST",
    )
    timeout = int(getattr(settings, "GROQ_TIMEOUT", 45))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        logger.warning("groq rejected status=%s body=%s", exc.code, detail)
        raise RuntimeError(f"Groq error ({exc.code}): {detail}") from exc


def run_assistant(user: User, messages: list, request) -> dict:
    cleaned = []
    for item in messages[-HISTORY_LIMIT:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            cleaned.append({"role": role, "content": content})
    if not cleaned:
        return {"reply": "Tell me what you need — look up tickets, a vendor's jobs, or lodge a new complaint."}

    model = getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")
    thread = [{"role": "system", "content": _system_prompt(user)}, *cleaned]
    last_complaint = None

    for _ in range(MAX_ROUNDS):
        data = _groq_chat(
            {
                "model": model,
                "messages": thread,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.2,
            }
        )
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            thread.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                fn = call.get("function") or {}
                raw_args = fn.get("arguments") or "{}"
                try:
                    parsed = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    parsed = {}
                result = run_tool(user, fn.get("name") or "", parsed, request)
                try:
                    payload = json.loads(result)
                    if payload.get("ok") and payload.get("complaint_id"):
                        last_complaint = payload["complaint_id"]
                except json.JSONDecodeError:
                    pass
                thread.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": fn.get("name"),
                        "content": result,
                    }
                )
            continue
        reply = (message.get("content") or "").strip()
        if not reply:
            reply = "I could not form a reply. Please try again."
        return {"reply": reply, "complaint_id": last_complaint}

    return {"reply": "I had to stop looking that up. Ask again with a shorter question.", "complaint_id": last_complaint}
