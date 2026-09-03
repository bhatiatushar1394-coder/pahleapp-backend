import json
import logging
import re
import time
import urllib.error
import urllib.request

from django.conf import settings

from django.db.models import Q

from .constants import match_subtype
from .models import Complaint, User, Vendor


logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_ROUNDS = 4
HISTORY_LIMIT = 8

GROQ_MODELS = (
    {
        "id": "openai/gpt-oss-120b",
        "label": "GPT-OSS 120B",
        "hint": "Best quality · free tier 8K tokens/min",
    },
    {
        "id": "openai/gpt-oss-20b",
        "label": "GPT-OSS 20B",
        "hint": "Faster · separate free-tier quota",
    },
    {
        "id": "qwen/qwen3.6-27b",
        "label": "Qwen 3.6 27B",
        "hint": "Alternate model · separate quota",
    },
)
ALLOWED_MODEL_IDS = {item["id"] for item in GROQ_MODELS}


class GroqRateLimit(RuntimeError):
    def __init__(self, retry_after: float, detail: str = ""):
        self.retry_after = max(0.0, float(retry_after or 0))
        super().__init__(detail or "Groq rate limit reached.")


def groq_model_catalog() -> dict:
    default = _resolve_model(None)
    return {"default": default, "models": list(GROQ_MODELS)}


def _resolve_model(requested: str | None) -> str:
    default = getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")
    if default not in ALLOWED_MODEL_IDS:
        default = "openai/gpt-oss-120b"
    candidate = (requested or "").strip() or default
    return candidate if candidate in ALLOWED_MODEL_IDS else default


def _fallback_models(primary: str) -> list[str]:
    return [item["id"] for item in GROQ_MODELS if item["id"] != primary]

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
                    "description": {"type": "string", "description": "The problem text. This is the only problem field — there is no separate specific_problem."},
                    "specific_problem": {
                        "type": "string",
                        "description": "Sub-category for the task type, e.g. Tank Leakage, Hose Pipe, Painting Work.",
                    },
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

When listing more than one complaint, use a GitHub-flavored markdown table with columns:
Complaint ID | Pump | Category | Sub-category | Status | Priority | Vendor | Created
Keep cell text short. Do not pad with spaces. After the table, add one short sentence if needed.

To RAISE a complaint:
1. Ask one missing thing at a time.
2. Need: category (Tank Related, DU related, Civil Work, Electrical Work, Others), matching sub-category, description, priority (Low / Medium / High).
3. Sub-categories: Tank Related = Water Ingress, Tank Leakage, Vent Pipe Issue, Fill Pipe Issue. DU related = Hose Pipe, Nozzle Issue, Keypad Problem, Electronics Parts Issue, Display Problem. Civil Work = Painting Work, Brickwork, Structural Work, Canopy Related. Electrical Work = Replacement of Servo, Replacement of CVT, Cable Related. Others has no sub-category.
4. If category is DU related, also ask Make, Model, Sr. No.
5. Customers use their mapped pump. Officers must pick a pump (use list_pumps).
6. Show a short summary and ask them to confirm.
7. When they say yes / confirm / lodge it, call lodge_complaint immediately with confirmed=true. Do not ask more questions.
8. Pass the sub-category in specific_problem. The description is the detailed problem.
9. Never lodge without confirmation.

Vendors cannot lodge complaints; they can only ask about jobs assigned to them.
Be concise. If a tool returns no rows, say you found none in their access — do not invent tickets.
"""


def _compact_complaint(c: Complaint) -> dict:
    return {
        "complaint_id": c.complaint_id,
        "pump": c.pump.name,
        "pump_code": c.pump.pump_code,
        "category": c.get_category_display(),
        "sub_category": c.specific_problem,
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
        description = (args.get("description") or "").strip()
        category = (args.get("category") or "").upper()
        from .constants import PROBLEM_MASTER, match_subtype

        subtype = match_subtype(category, args.get("specific_problem"), description)
        if PROBLEM_MASTER.get(category) and not subtype:
            return _dumps(
                {
                    "error": "Select a sub-category for this task type.",
                    "sub_categories": PROBLEM_MASTER.get(category),
                }
            )
        payload = {
            "category": category,
            "description": description,
            "specific_problem": subtype or "Others",
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


def _retry_after(exc: urllib.error.HTTPError, body: str) -> float:
    header = exc.headers.get("Retry-After") or exc.headers.get("retry-after") if exc.headers else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = re.search(r"try again in ([\d.]+)s", body, re.I)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 6.0


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
        if exc.code == 429:
            raise GroqRateLimit(_retry_after(exc, detail), detail) from exc
        raise RuntimeError(f"Groq error ({exc.code}): {detail}") from exc


def _groq_chat_with_fallback(body: dict) -> tuple[dict, str]:
    primary = body.get("model") or _resolve_model(None)
    last_limit: GroqRateLimit | None = None
    for index, candidate in enumerate([primary, *_fallback_models(primary)]):
        payload = {**body, "model": candidate}
        try:
            return _groq_chat(payload), candidate
        except GroqRateLimit as exc:
            last_limit = exc
            if index == 0:
                wait = min(max(exc.retry_after, 1.0), 8.0)
                logger.info("groq 429 on %s, retrying in %.1fs", candidate, wait)
                time.sleep(wait)
                try:
                    return _groq_chat(payload), candidate
                except GroqRateLimit as retry_exc:
                    last_limit = retry_exc
                    logger.info("groq still 429 on %s, switching model", candidate)
                    continue
            logger.info("groq 429 on %s, trying next model", candidate)
    wait = last_limit.retry_after if last_limit else 6.0
    raise GroqRateLimit(
        wait,
        "All Groq models are rate-limited right now. Wait a few seconds, or pick another model and send again.",
    )


_CONFIRM_RE = re.compile(
    r"(?i)^\s*(yes|y|yeah|yep|ok|okay|sure|confirm(ed)?|please\s+lodge|lodge(\s+it)?|go\s+ahead|proceed|do\s+it|create\s+it)\b"
)
_CATEGORY_PATTERNS = (
    (r"\b(du[\s-]*related|category\s*[:\-]\s*du|dispensing\s*unit)\b", "DU"),
    (r"\b(tank[\s-]*related|category\s*[:\-]\s*tank)\b", "TANK"),
    (r"\b(civil[\s-]*work|category\s*[:\-]\s*civil)\b", "CIVIL"),
    (r"\b(electrical[\s-]*work|category\s*[:\-]\s*electrical)\b", "ELECTRICAL"),
    (r"\b(others?|category\s*[:\-]\s*other)\b", "OTHER"),
)


def _is_confirm(text: str) -> bool:
    return bool(_CONFIRM_RE.match((text or "").strip()))


def _field(blob: str, *names: str) -> str:
    for name in names:
        match = re.search(rf"(?im)^\s*{name}\s*[:\-]\s*(.+)$", blob)
        if match:
            return match.group(1).strip().strip("*").strip()
    return ""


def _extract_lodge_args(user: User, messages: list) -> dict | None:
    blob = "\n".join((item.get("content") or "") for item in messages)
    category = ""
    for pattern, code in _CATEGORY_PATTERNS:
        if re.search(pattern, blob, re.I):
            category = code
            break
    description = _field(blob, "Description", "Problem", "Issue")
    if not description:
        for item in reversed(messages):
            if item.get("role") != "user":
                continue
            text = (item.get("content") or "").strip()
            if text and not _is_confirm(text) and len(text) > 4:
                description = text
                break
    if not category or not description:
        return None

    priority = "MEDIUM"
    pr = _field(blob, "Priority") or ""
    if re.search(r"\bhigh\b", pr, re.I) or (not pr and re.search(r"(?i)priority\s*[:\-]\s*high", blob)):
        priority = "HIGH"
    elif re.search(r"\blow\b", pr, re.I):
        priority = "LOW"

    make = _field(blob, "DU Make", "Make")
    model = _field(blob, "DU Model", "Model")
    serial = _field(blob, "Sr\\.?\\s*No\\.?", "Serial", "DU Serial")
    combo = re.search(
        r"(?i)(?:du\s*)?(?:make\s*/\s*model\s*/\s*(?:sr\.?\s*no\.?|serial))\s*[:\-]\s*([^/\n]+)/([^/\n]+)/(\S+)",
        blob,
    )
    if combo:
        make = make or combo.group(1).strip()
        model = model or combo.group(2).strip()
        serial = serial or combo.group(3).strip()

    args = {
        "confirmed": True,
        "category": category,
        "description": description[:2000],
        "specific_problem": match_subtype(category, description) or description[:200],
        "priority": priority,
        "du_make": make,
        "du_model": model,
        "du_serial": serial,
    }
    if user.role != User.Role.CP_USER:
        from .views import scoped_pumps

        pump_name = _field(blob, "Pump")
        qs = scoped_pumps(user)
        pump = None
        if pump_name:
            pump = qs.filter(Q(name__icontains=pump_name) | Q(pump_code__icontains=pump_name)).first()
        if pump is None and qs.count() == 1:
            pump = qs.first()
        if pump is None:
            return None
        args["pump_id"] = pump.id
    return args


def _direct_lodge(user: User, messages: list, request) -> dict | None:
    args = _extract_lodge_args(user, messages)
    if not args:
        return None
    raw = run_tool(user, "lodge_complaint", args, request)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not payload.get("ok"):
        logger.info("direct lodge skipped: %s", payload)
        return None
    cid = payload.get("complaint_id")
    pump = payload.get("pump") or ""
    return {
        "reply": f"Complaint **{cid}** has been lodged" + (f" for {pump}" if pump else "") + ". You can open it from Complaints.",
        "complaint_id": cid,
        "model": "direct",
        "switched_from": None,
    }


def run_assistant(user: User, messages: list, request, model: str | None = None) -> dict:
    cleaned = []
    for item in messages[-HISTORY_LIMIT:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            cleaned.append({"role": role, "content": content})
    if not cleaned:
        return {"reply": "Tell me what you need — look up tickets, a vendor's jobs, or lodge a new complaint."}

    last_user = next((item["content"] for item in reversed(cleaned) if item["role"] == "user"), "")
    if _is_confirm(last_user):
        lodged = _direct_lodge(user, cleaned, request)
        if lodged:
            return lodged

    model = _resolve_model(model)
    started_on = model
    thread = [{"role": "system", "content": _system_prompt(user)}, *cleaned]
    last_complaint = None

    try:
        for _ in range(MAX_ROUNDS):
            data, model = _groq_chat_with_fallback(
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
            return {
                "reply": reply,
                "complaint_id": last_complaint,
                "model": model,
                "switched_from": None if model == started_on else started_on,
            }
    except GroqRateLimit:
        if _is_confirm(last_user):
            lodged = _direct_lodge(user, cleaned, request)
            if lodged:
                return lodged
            return {
                "reply": "Groq is rate-limited, so I could not lodge via the model. Send **Yes** again after the summary is on screen, or use **+ New Complaint**. Wait about 20 seconds if it still fails.",
                "complaint_id": None,
                "model": started_on,
                "switched_from": None,
            }
        raise

    return {
        "reply": "I had to stop looking that up. Ask again with a shorter question.",
        "complaint_id": last_complaint,
        "model": model,
        "switched_from": None if model == started_on else started_on,
    }
