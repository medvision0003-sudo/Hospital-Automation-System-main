"""
Emergency Mapping Utility

Centralised helper for translating legacy emergency type strings
to clean EmergencyTypeEnum values. Used by the API gateway route
and tests to ensure backwards compatibility when old payloads
(e.g. "CODE_BLUE", "ACCIDENT") arrive from external callers.

This module owns the legacy translation mapping so that no single
route or test file has to duplicate the business logic.
"""


# Legacy emergency type values that were removed from EmergencyTypeEnum.
# Maps old string -> new clean EmergencyTypeEnum value string.
LEGACY_EMERGENCY_TRANSLATIONS: dict[str, str] = {
    "CODE_BLUE": "PATIENT_COLLAPSE",
    "ACCIDENT": "MASS_CASUALTY",
    "SECURITY_INCIDENT": "COMBATIVE_PERSON",
    "EQUIPMENT_FAILURE": "MASS_CASUALTY",
}


def translate_emergency_type(raw_type: str) -> str:
    """Translate a raw emergency type string to its clean enum value.

    If the input is a recognised legacy value it is mapped to the
    corresponding new EmergencyTypeEnum string.  Otherwise the
    original value is returned unchanged (the caller is responsible
    for final enum validation).

    Args:
        raw_type: Raw emergency type string from an incoming payload.

    Returns:
        Translated (or unchanged) emergency type string.
    """
    if not raw_type:
        return raw_type
    normalised = raw_type.strip().upper()
    return LEGACY_EMERGENCY_TRANSLATIONS.get(normalised, normalised)
