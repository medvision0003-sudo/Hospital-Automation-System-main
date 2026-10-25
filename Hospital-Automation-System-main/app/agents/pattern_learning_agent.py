import hashlib
import math
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.automation_recommendation import AutomationRecommendation
from app.models.automation_rule_audit import AutomationRuleAudit
from app.models.nursing_shift_log import NursingShiftLog


MIN_OBSERVATIONS = 10
MIN_OCCURRENCES = 3
MIN_FREQUENCY = 0.10
MAX_EVIDENCE_IDS = 20

SIGNALS = {
    "staffing_shortage": {
        "aliases": ("staffing status",),
        "title": "Staffing shortage",
        "matches": ("short staff", "shortage", "understaffed", "insufficient staff"),
        "benefit": "Prompt a supervisor to review recurring staffing concerns.",
    },
    "medication_delay": {
        "aliases": ("were all medicines given on time", "medication delay"),
        "title": "Medication delay reported",
        "matches": ("no", "delayed", "not on time", "late"),
        "benefit": "Prompt a supervisor to review reported medication-timing delays.",
    },
    "equipment_malfunction": {
        "aliases": ("any equipment malfunction", "equipment malfunction"),
        "title": "Equipment malfunction reported",
        "matches": ("yes", "true", "malfunction", "not working"),
        "benefit": "Prompt a supervisor to review reported equipment concerns.",
    },
    "handover_issue": {
        "aliases": ("was proper handover given", "handover"),
        "title": "Handover concern reported",
        "matches": ("no", "incomplete", "not given", "not proper"),
        "benefit": "Prompt a supervisor to review recurring handover concerns.",
    },
    "emergency_reported": {
        "aliases": ("any emergency during shift", "emergency"),
        "title": "Emergency reported",
        "matches": ("yes", "true"),
        "benefit": "Prompt a supervisor to review and route the report through established procedures.",
    },
    "consumable_shortage": {
        "aliases": ("consumables running low", "consumable"),
        "title": "Consumables running low",
        "matches": (),
        "benefit": "Prompt a supervisor to review reported consumable needs.",
    },
    "pending_tasks": {
        "aliases": ("pending tasks for next shift", "pending tasks"),
        "title": "Tasks handed over to the next shift",
        "matches": (),
        "benefit": "Prompt a supervisor to review recurring shift handover tasks.",
    },
}


def _normalize(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if item is not None).strip().lower()
    if isinstance(value, dict):
        return ", ".join(str(item) for item in value.values() if item is not None).strip().lower()
    return str(value).strip().lower() if value is not None else ""


def _answer_for(answers: dict, aliases: tuple[str, ...]) -> str | None:
    for key, value in answers.items():
        key_normalized = str(key).strip().lower()
        if any(alias in key_normalized for alias in aliases):
            normalized = _normalize(value)
            if normalized and normalized not in {"unknown", "n/a", "na"}:
                return normalized
    return None


def _is_signal(signal_type: str, value: str) -> bool:
    value = value.strip().lower()
    if signal_type in {"consumable_shortage", "pending_tasks"}:
        values = [part.strip() for part in value.split(",")]
        return any(
            part
            and part not in {"none", "no", "n/a", "na"}
            and not part.startswith(("no ", "none "))
            for part in values
        )
    if signal_type == "staffing_shortage":
        if any(phrase in value for phrase in ("not short", "no shortage", "not understaffed")):
            return False
    elif signal_type == "medication_delay":
        if any(phrase in value for phrase in ("no delay", "no delays", "not delayed", "no late")):
            return False
        if value.startswith(("yes", "true")):
            return False
        if value.startswith(("no", "false")):
            return True
        return any(phrase in value for phrase in ("delayed", "not on time", "late"))
    elif signal_type == "equipment_malfunction":
        if any(phrase in value for phrase in ("not malfunction", "no equipment issue")):
            return False
        if value.startswith(("no", "false")) and not value.startswith("not working"):
            return False
    elif signal_type == "handover_issue":
        if "not proper handover" in value or "not properly handed over" in value:
            return True
        if any(phrase in value for phrase in ("no issue", "no concern", "proper handover")):
            return False
        if value.startswith(("yes", "true")):
            return False
    elif signal_type == "emergency_reported":
        return value.startswith(("yes", "true"))
    return any(phrase in value for phrase in SIGNALS[signal_type]["matches"])


def _wilson_lower_bound(successes: int, total: int) -> float:
    if total == 0:
        return 0.0
    z = 1.96
    proportion = successes / total
    denominator = 1 + z * z / total
    center = proportion + z * z / (2 * total)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    )
    return max(0.0, (center - margin) / denominator)


def _pattern_key(signal_type: str, ward_area: str | None, shift_name: str | None) -> str:
    raw = "|".join((signal_type, ward_area or "*", shift_name or "*")).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PatternLearningAgent:
    """Find recurring operational signals in submitted shift reports."""

    def analyze(self, db: Session) -> dict:
        reports = db.query(NursingShiftLog).order_by(NursingShiftLog.shift_date.asc()).all()
        groups: dict[tuple[str, str | None, str | None], dict] = defaultdict(
            lambda: {"observations": 0, "occurrences": 0, "ids": [], "dates": []}
        )

        for report in reports:
            answers = report.answers if isinstance(report.answers, dict) else {}
            for signal_type, definition in SIGNALS.items():
                value = _answer_for(answers, definition["aliases"])
                if value is None:
                    continue
                is_present = _is_signal(signal_type, value)
                scopes = (
                    (None, None),
                    (report.ward_area, None),
                    (None, report.shift_name),
                    (report.ward_area, report.shift_name),
                )
                for ward_area, shift_name in scopes:
                    group = groups[(signal_type, ward_area, shift_name)]
                    group["observations"] += 1
                    group["dates"].append(report.shift_date)
                    if is_present:
                        group["occurrences"] += 1
                        if len(group["ids"]) < MAX_EVIDENCE_IDS:
                            group["ids"].append(report.log_id)

        created = 0
        updated = 0
        recommendations = []
        for (signal_type, ward_area, shift_name), group in groups.items():
            total = group["observations"]
            occurrences = group["occurrences"]
            frequency = occurrences / total if total else 0.0
            if (
                total < MIN_OBSERVATIONS
                or occurrences < MIN_OCCURRENCES
                or frequency < MIN_FREQUENCY
            ):
                continue

            definition = SIGNALS[signal_type]
            scope = ", ".join(value for value in (ward_area, shift_name) if value)
            description = (
                f"{definition['title']} was reported in {occurrences} of {total} "
                f"observed reports"
                + (f" for {scope}" if scope else " across all wards and shifts")
                + ". This is a recurrence signal, not a clinical recommendation."
            )
            key = _pattern_key(signal_type, ward_area, shift_name)
            recommendation = (
                db.query(AutomationRecommendation)
                .filter(AutomationRecommendation.pattern_key == key)
                .first()
            )
            latest_date = max(group["dates"]) if group["dates"] else None
            earliest_date = min(group["dates"]) if group["dates"] else None

            if recommendation is None:
                recommendation = AutomationRecommendation(
                    pattern_key=key,
                    pattern_type=signal_type,
                    description=description,
                    occurrences=occurrences,
                    observations=total,
                    frequency=frequency,
                    confidence=_wilson_lower_bound(occurrences, total),
                    period_start=earliest_date,
                    period_end=latest_date,
                    ward_area=ward_area,
                    shift_name=shift_name,
                    supporting_record_ids=group["ids"],
                    suggested_action="CREATE_SUPERVISOR_TASK_REQUEST",
                    expected_benefit=definition["benefit"],
                    risk_level="OPERATIONAL_REVIEW",
                    status="PENDING_APPROVAL",
                )
                db.add(recommendation)
                db.flush()
                db.add(
                    AutomationRuleAudit(
                        recommendation_id=recommendation.recommendation_id,
                        action="RECOMMENDATION_CREATED",
                        previous_state=None,
                        new_state={
                            "status": "PENDING_APPROVAL",
                            "occurrences": occurrences,
                            "observations": total,
                            "frequency": frequency,
                        },
                        notes="Generated from historical shift-report recurrence analysis.",
                    )
                )
                created += 1
            elif recommendation.status == "PENDING_APPROVAL":
                previous_state = {
                    "status": recommendation.status,
                    "occurrences": recommendation.occurrences,
                    "observations": recommendation.observations,
                    "frequency": recommendation.frequency,
                }
                recommendation.description = description
                recommendation.occurrences = occurrences
                recommendation.observations = total
                recommendation.frequency = frequency
                recommendation.confidence = _wilson_lower_bound(occurrences, total)
                recommendation.period_start = earliest_date
                recommendation.period_end = latest_date
                recommendation.supporting_record_ids = group["ids"]
                db.add(
                    AutomationRuleAudit(
                        recommendation_id=recommendation.recommendation_id,
                        action="RECOMMENDATION_REFRESHED",
                        previous_state=previous_state,
                        new_state={
                            "status": recommendation.status,
                            "occurrences": occurrences,
                            "observations": total,
                            "frequency": frequency,
                        },
                        notes="Pending recommendation refreshed from current historical reports.",
                    )
                )
                updated += 1

            recommendations.append(recommendation)

        db.commit()
        for recommendation in recommendations:
            db.refresh(recommendation)
        return {
            "reports_analyzed": len(reports),
            "created": created,
            "updated": updated,
            "recommendations": recommendations,
        }

    @staticmethod
    def matches(report: NursingShiftLog, rule_conditions: dict) -> tuple[bool, dict]:
        signal_type = rule_conditions.get("signal_type")
        definition = SIGNALS.get(signal_type)
        answers = report.answers if isinstance(report.answers, dict) else {}
        value = _answer_for(answers, definition["aliases"]) if definition else None
        checks = {
            "signal_type": signal_type in SIGNALS,
            "signal_present": bool(value and _is_signal(signal_type, value))
            if signal_type in SIGNALS
            else False,
            "ward_area": not rule_conditions.get("ward_area")
            or rule_conditions["ward_area"] == report.ward_area,
            "shift_name": not rule_conditions.get("shift_name")
            or rule_conditions["shift_name"] == report.shift_name,
        }
        return all(checks.values()), checks
