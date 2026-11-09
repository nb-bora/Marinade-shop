"""English catalogue. Mirrors ``messages_fr``: same keys, same ``{placeholders}``.

Keys missing here fall back to the French text (see ``app.i18n.t``), so this file can be
completed incrementally.
"""

MESSAGES = {
    # Generic errors
    "common.error": "An error occurred.",
    "common.validation_error": "The submitted data is invalid.",
    "common.not_found": "Resource not found.",
    "common.conflict": "Conflict with an existing resource.",
    "common.business_rule": "Operation refused by business rules.",
    "common.database_error": "Database error.",
    # Authentication
    "auth.authentication_failed": "Authentication failed.",
    "auth.forbidden": "Access denied.",
    "auth.activation_required": "Your account is not activated yet. Enter the code sent by email.",
    "auth.activation_code_invalid": "Incorrect activation code.",
    "auth.activation_code_expired": "This code has expired. Request a new one.",
    "auth.activation_too_many_attempts": "Too many incorrect attempts. Request a new code.",
    # HTTP
    "http.bad_request": "Invalid request.",
    "http.unauthorized": "Authentication required.",
    "http.forbidden": "Access denied.",
    "http.not_found": "Resource not found.",
    "http.method_not_allowed": "Method not allowed.",
    "http.not_acceptable": "Requested response format not acceptable.",
    "http.conflict": "Conflict with an existing resource.",
    "http.gone": "Resource no longer available.",
    "http.payload_too_large": "Request too large.",
    "http.unsupported_media_type": "Unsupported content type.",
    "http.unprocessable": "Data could not be processed.",
    "http.too_many_requests": "Too many requests, please retry later.",
    "http.internal_error": "Internal server error.",
    "http.bad_gateway": "Bad gateway.",
    "http.service_unavailable": "Service temporarily unavailable.",
    "http.error": "Error.",
    "http.title.default": "Error",
    "http.title.400": "Bad request",
    "http.title.401": "Unauthenticated",
    "http.title.403": "Access denied",
    "http.title.404": "Not found",
    "http.title.409": "Conflict",
    "http.title.422": "Invalid data",
    "http.title.429": "Too many requests",
    "http.title.500": "Internal error",
    # Validation (Pydantic)
    "validation.failed": "{count} validation errors.",
    "validation.failed_one": "Field “{field}”: {detail}",
    "validation.invalid": "Invalid value.",
    "validation.missing": "Required field missing.",
    "validation.string_too_short": "At least {min_length} characters.",
    "validation.string_too_long": "At most {max_length} characters.",
    "validation.int_parsing": "Integer expected.",
    "validation.float_parsing": "Number expected.",
    "validation.greater_than": "Must be greater than {gt}.",
    "validation.greater_than_equal": "Must be greater than or equal to {ge}.",
    "validation.less_than": "Must be less than {lt}.",
    "validation.less_than_equal": "Must be less than or equal to {le}.",
    "validation.uuid_parsing": "UUID expected.",
    "validation.date_parsing": "Date expected in YYYY-MM-DD format.",
    "validation.datetime_parsing": "Date and time expected in ISO 8601 format.",
    "validation.bool_parsing": "Boolean expected.",
    "validation.extra_forbidden": "Field not allowed.",
    "validation.literal_error": "Value not allowed.",
    "validation.value_error": "Invalid value.",
    "validation.assertion_error": "Invalid value.",
    # Stock
    "stock.insufficient": "Insufficient stock for this request.",
}


from app.i18n.messages_fiches import EN as _FICHES_EN  # noqa: E402

MESSAGES.update(_FICHES_EN)
