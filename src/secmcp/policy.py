"""Política de flujo para herramientas de un agente.

Idea central (la "tríada letal"): un agente es explotable por exfiltración cuando reúne a la vez
(1) acceso a datos privados, (2) exposición a contenido no confiable y (3) una vía de salida.
La política corta esa combinación en vez de intentar adivinar cada ataque:

  * default-deny: una herramienta sin ficha no se ejecuta.
  * etiquetado de contaminación (taint): leer contenido no confiable o privado marca la sesión.
  * vía de salida (sink): se bloquea si la sesión está contaminada con contenido no confiable
    Y vio datos privados, salvo aprobación humana explícita.
  * lista blanca de destinos de salida, siempre, aprobada o no.
  * se bloquean argumentos de salida que contengan canarios o secretos.
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import scanners


class Verdict(str, enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    NEEDS_APPROVAL = "needs_approval"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    reads_private: bool = False      # devuelve datos privados
    returns_untrusted: bool = False  # devuelve contenido que puede venir de terceros
    sink: bool = False               # envía datos fuera del sistema
    destination_arg: str | None = None  # argumento que lleva el destino (URL o email)


@dataclass
class Decision:
    verdict: Verdict
    reason: str
    rule: str


@dataclass
class Session:
    private_seen: bool = False
    untrusted_seen: bool = False
    approvals: set[str] = field(default_factory=set)  # ids de aprobación humana concedidos
    audit: list[dict] = field(default_factory=list)


@dataclass
class Policy:
    tools: dict[str, ToolSpec]
    allowed_domains: frozenset[str] = frozenset()
    canaries: frozenset[str] = frozenset()

    def _domain(self, dest: str) -> str:
        if "@" in dest and "://" not in dest:
            return dest.rsplit("@", 1)[1].lower().strip()
        host = urlparse(dest if "://" in dest else f"//{dest}").hostname
        return (host or "").lower()

    def domain_allowed(self, dest: str) -> bool:
        d = self._domain(dest)
        if not d:
            return False
        return any(d == a or d.endswith("." + a) for a in self.allowed_domains)

    def check(self, session: Session, name: str, args: dict, approval_id: str | None = None) -> Decision:
        spec = self.tools.get(name)
        if spec is None:
            return self._log(session, name, Decision(Verdict.DENY, "herramienta desconocida", "default-deny"))
        if not spec.sink:
            return self._log(session, name, Decision(Verdict.ALLOW, "no es vía de salida", "non-sink"))

        flat = " ".join(str(v) for v in args.values())
        if scanners.contains_canary(flat, set(self.canaries)):
            return self._log(session, name, Decision(Verdict.DENY, "el argumento contiene un canario", "canary"))
        kinds = [k for k in scanners.secret_kinds(flat) if k != "email"]
        if kinds:
            return self._log(session, name, Decision(Verdict.DENY, f"el argumento contiene secretos ({', '.join(kinds)})", "secret-in-args"))

        dest = str(args.get(spec.destination_arg, "")) if spec.destination_arg else ""
        if not self.domain_allowed(dest):
            return self._log(session, name, Decision(Verdict.DENY, f"destino fuera de la lista blanca: {self._domain(dest) or 'vacío'}", "egress-allowlist"))

        if session.private_seen and session.untrusted_seen:
            if approval_id and approval_id in session.approvals:
                return self._log(session, name, Decision(Verdict.ALLOW, "aprobado por una persona", "human-approved"))
            return self._log(session, name, Decision(Verdict.NEEDS_APPROVAL, "la sesión tiene datos privados y contenido no confiable", "lethal-trifecta"))
        return self._log(session, name, Decision(Verdict.ALLOW, "destino permitido y sesión sin la combinación riesgosa", "sink-ok"))

    def observe(self, session: Session, name: str) -> None:
        """Actualiza la contaminación después de una llamada permitida."""
        spec = self.tools.get(name)
        if not spec:
            return
        session.private_seen |= spec.reads_private
        session.untrusted_seen |= spec.returns_untrusted

    @staticmethod
    def _log(session: Session, name: str, d: Decision) -> Decision:
        session.audit.append({"tool": name, "verdict": d.verdict.value, "rule": d.rule, "reason": d.reason})
        return d


_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def valid_approval_id(x: str) -> bool:
    return bool(_ID.match(x))
