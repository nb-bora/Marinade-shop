"""Mise en page commune des emails Marinade (carte claire, pastille de statut, bloc de détails,
total, bouton pleine largeur, référence, pied de page).

HTML « email-safe » : tables, styles en ligne, aucune image distante ni police externe. Le
mode sombre est géré par ``prefers-color-scheme`` là où le client le permet. Tout texte inséré
est échappé ; la version texte brut reprend la même structure.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from app.core.config import settings

ORANGE = "#E67E22"
ORANGE_DARK = "#B85F0F"
ORANGE_SOFT = "#FDF1E3"

# ton -> (fond de la pastille, texte, point)
TONS = {
    "info": ("#EAF2FD", "#1F5FAE", "#2F7DE1"),
    "success": ("#E6F6EC", "#1B7A41", "#2DB35F"),
    "warning": ("#FFF3DC", "#9A6400", "#F2A100"),
    "danger": ("#FDE9E8", "#B3261E", "#E5483E"),
    "brand": (ORANGE_SOFT, ORANGE_DARK, ORANGE),
}


@dataclass
class Status:
    label: str
    tone: str = "info"


@dataclass
class Hero:
    """Deux repères de part et d'autre d'une flèche (ex. dépôt → retrait)."""

    left_title: str
    left_sub: str = ""
    right_title: str = ""
    right_sub: str = ""


@dataclass
class Details:
    title: str = ""
    badge: str = ""
    hero: Optional[Hero] = None
    rows: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class Stat:
    label: str
    value: str
    unit: str = ""


def _e(value: str) -> str:
    return html.escape(str(value), quote=True)


def _br(value: str) -> str:
    return _e(value).replace("\n", "<br>")


STYLE = """
@media (prefers-color-scheme: dark) {
  body, .bg { background:#14141a !important; }
  .card { background:#1e1e26 !important; border-color:#2c2c37 !important; }
  .panel { background:#272731 !important; }
  .t1 { color:#f3f3f7 !important; } .t2 { color:#b9b9c6 !important; } .t3 { color:#8b8b99 !important; }
  .line { border-color:#33333f !important; }
}
@media only screen and (max-width: 480px) { .pad { padding:22px 18px !important; } }
"""


def _pill(status: Status) -> str:
    bg, fg, dot = TONS.get(status.tone, TONS["info"])
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};font-size:12px;'
        f'font-weight:600;line-height:1;padding:7px 12px;border-radius:999px">'
        f'<span style="color:{dot};font-size:10px;vertical-align:1px">&#9679;</span>&nbsp; '
        f"{_e(status.label)}</span>"
    )


def _details_html(d: Details) -> str:
    head = ""
    if d.title or d.badge:
        badge = (
            f'<span style="display:inline-block;background:{ORANGE_SOFT};color:{ORANGE_DARK};'
            f'font-size:11px;font-weight:600;padding:5px 10px;border-radius:999px">{_e(d.badge)}</span>'
            if d.badge
            else ""
        )
        head = (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td class="t3" style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;'
            f'font-weight:600;color:#9a9188">{_e(d.title)}</td>'
            f'<td align="right">{badge}</td></tr></table>'
        )
    hero = ""
    if d.hero:
        h = d.hero
        hero = (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            'style="margin-top:14px"><tr>'
            f'<td valign="top"><div class="t1" style="font-size:17px;font-weight:700;color:#23232e">'
            f'{_e(h.left_title)}</div><div class="t3" style="font-size:12px;color:#9a9188;'
            f'margin-top:4px">{_e(h.left_sub)}</div></td>'
            '<td align="center" width="40" class="t3" style="font-size:18px;color:#b9b0a6">&rarr;</td>'
            f'<td valign="top" align="right"><div class="t1" style="font-size:17px;font-weight:700;'
            f'color:#23232e">{_e(h.right_title)}</div><div class="t3" style="font-size:12px;'
            f'color:#9a9188;margin-top:4px">{_e(h.right_sub)}</div></td></tr></table>'
        )
    rows = ""
    for i, (k, v) in enumerate(d.rows):
        border = "border-top:1px solid #efe7de;" if (i or hero or head) else ""
        rows += (
            f'<tr><td class="t2 line" style="{border}padding:9px 0;font-size:13px;color:#7a7168">'
            f'{_e(k)}</td><td class="t1 line" align="right" style="{border}padding:9px 0;'
            f'font-size:13px;font-weight:600;color:#23232e">{_br(v)}</td></tr>'
        )
    table = (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'style="margin-top:{10 if (hero or head) else 0}px">{rows}</table>'
        if rows
        else ""
    )
    return (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="margin:22px 0 0"><tr><td class="panel" style="background:#faf6f1;'
        f'border-radius:16px;padding:18px 20px">{head}{hero}{table}</td></tr></table>'
    )


def _stats_html(stats: Sequence[Stat]) -> str:
    cells = ""
    for i, s in enumerate(stats[:2]):
        align = "left" if i == 0 else "right"
        unit = (
            f' <span class="t3" style="font-size:12px;font-weight:500;color:#9a9188">{_e(s.unit)}</span>'
            if s.unit
            else ""
        )
        cells += (
            f'<td align="{align}" valign="bottom"><div class="t3" style="font-size:11px;'
            f'letter-spacing:.08em;text-transform:uppercase;font-weight:600;color:#9a9188">'
            f'{_e(s.label)}</div><div class="t1" style="font-size:26px;font-weight:700;'
            f'color:#23232e;margin-top:6px">{_e(s.value)}{unit}</div></td>'
        )
    return (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'class="line" style="margin-top:22px;border-top:1px solid #ece6df"><tr>'
        f'<td style="padding-top:18px"><table role="presentation" width="100%" cellspacing="0" '
        f'cellpadding="0"><tr>{cells}</tr></table></td></tr></table>'
    )


def render_email(
    *,
    title: str,
    greeting: str,
    paragraphs: Sequence[str] = (),
    action_label: Optional[str] = None,
    action_url: Optional[str] = None,
    code: Optional[str] = None,
    note: Optional[str] = None,
    signature: str = "",
    status: Optional[Status] = None,
    details: Optional[Details] = None,
    stats: Sequence[Stat] = (),
    reference: Optional[str] = None,
    footer: Optional[str] = None,
    lang: str = "fr",
) -> Tuple[str, str]:
    """Retourne ``(texte brut, html)``. ``title`` sert d'objet/titre de page ; le titre visible
    de la carte est ``greeting`` (comme « Bonjour Brice, »)."""
    brand = settings.EMAIL_FROM_NAME
    auto = footer or (
        "E-mail automatique Marinade" if lang == "fr" else "Automated email from Marinade"
    )
    tagline = (
        "Marinade — gestion de restaurants et de pressings"
        if lang == "fr"
        else "Marinade — restaurant and laundry management"
    )

    # ---- texte brut
    t: List[str] = []
    if status:
        t.append(f"[{status.label}]")
    t += [greeting, ""]
    t += [p for p in paragraphs]
    if details:
        t.append("")
        if details.title:
            t.append(details.title.upper() + (f" ({details.badge})" if details.badge else ""))
        if details.hero:
            h = details.hero
            t.append(f"{h.left_title} ({h.left_sub}) -> {h.right_title} ({h.right_sub})")
        t += [f"- {k} : {v}" for k, v in details.rows]
    for s in stats:
        t.append(f"{s.label} : {s.value} {s.unit}".rstrip())
    if action_url:
        t += ["", f"{action_label or 'Lien'} : {action_url}"]
    if code:
        t += ["", f"Code : {code}"]
    if note:
        t += ["", note]
    if signature:
        t += ["", signature]
    if reference:
        t += ["", f"Réf. {reference}"]
    t += ["", auto]
    text = "\n".join(t)

    # ---- html
    body = "".join(
        f'<p class="t2" style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#6b6b7b">'
        f"{_br(p)}</p>"
        for p in paragraphs
    )
    pill = f'<div style="margin:22px 0 14px">{_pill(status)}</div>' if status else ""
    button = (
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'style="margin-top:24px"><tr><td align="center" bgcolor="{ORANGE}" '
        f'style="border-radius:12px"><a href="{_e(action_url)}" style="display:block;'
        f'padding:14px 20px;color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;'
        f'border-radius:12px">{_e(action_label or "Ouvrir")}</a></td></tr></table>'
        if action_url
        else ""
    )
    link_fallback = (
        f'<p class="t3" style="margin:12px 0 0;font-size:11px;color:#a49b92;word-break:break-all;'
        f'text-align:center">{_e(action_url)}</p>'
        if action_url
        else ""
    )
    code_block = (
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'style="margin-top:20px"><tr><td class="panel" align="center" style="background:#faf6f1;'
        f"border-radius:14px;padding:16px;font-size:28px;letter-spacing:8px;font-weight:700;"
        f'color:{ORANGE_DARK}">{_e(code)}</td></tr></table>'
        if code
        else ""
    )
    note_block = (
        f'<p class="t3" style="margin:20px 0 0;font-size:12px;line-height:1.55;color:#9a9188">'
        f"{_br(note)}</p>"
        if note
        else ""
    )
    sign_block = (
        f'<p class="t2" style="margin:22px 0 0;font-size:13px;color:#6b6b7b">{_e(signature)}</p>'
        if signature
        else ""
    )
    ref_block = (
        f'<p class="t3" style="margin:22px 0 0;text-align:center;font-size:11px;color:#b3aaa0">'
        f"Réf. {_e(reference)}</p>"
        if reference
        else ""
    )
    page = f"""<!doctype html>
<html lang="{_e(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>{_e(title)}</title><style>{STYLE}</style></head>
<body class="bg" style="margin:0;padding:0;background:#f3f1ee;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<table role="presentation" class="bg" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f1ee">
<tr><td align="center" style="padding:28px 12px">
<table role="presentation" class="card" width="520" cellspacing="0" cellpadding="0" style="max-width:520px;width:100%;background:#ffffff;border:1px solid #ebe5de;border-radius:24px">
<tr><td class="pad" style="padding:28px 30px 26px">
<table role="presentation" cellspacing="0" cellpadding="0"><tr>
<td width="36" height="36" align="center" bgcolor="{ORANGE}" style="border-radius:10px;color:#ffffff;font-size:18px;font-weight:800">M</td>
<td class="t1" style="padding-left:12px;font-size:15px;font-weight:700;color:#23232e">{_e(brand)}</td></tr></table>
{pill}
<h1 class="t1" style="margin:{0 if status else 24}px 0 12px;font-size:24px;line-height:1.25;font-weight:700;color:#23232e">{_e(greeting)}</h1>
{body}{_details_html(details) if details else ""}{_stats_html(stats) if stats else ""}{code_block}{button}{link_fallback}{note_block}{sign_block}{ref_block}
<p class="t3" style="margin:18px 0 0;text-align:center;font-size:11px;color:#b3aaa0">{_e(auto)}</p>
</td></tr></table>
<p class="t3" style="margin:16px 0 0;font-size:11px;color:#a49b92;text-align:center">{_e(tagline)}</p>
</td></tr></table></body></html>"""
    return text, page
