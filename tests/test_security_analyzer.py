import pytest

from agent_veriq.core.security_analyzer import (
    AuthStatus,
    SecuritySource,
    analyze_operation_security,
    find_security_gaps,
    security_overview,
)


@pytest.fixture
def spec(load_fixture):
    return load_fixture("security_mixed.yaml")


def _analyze(spec, operation_id):
    return analyze_operation_security(spec, spec.find_operation(operation_id))


@pytest.mark.parametrize(
    ("operation_id", "status", "source"),
    [
        ("publicOp", AuthStatus.NONE_DECLARED, SecuritySource.OPERATION_EMPTY_OVERRIDE),
        ("inheritedOp", AuthStatus.DECLARED_REQUIRED, SecuritySource.GLOBAL),
        ("alternativesOp", AuthStatus.DECLARED_REQUIRED, SecuritySource.OPERATION),
        ("combinedOp", AuthStatus.DECLARED_REQUIRED, SecuritySource.OPERATION),
        ("optionalOp", AuthStatus.NONE_DECLARED, SecuritySource.OPERATION),
        ("unknownOp", AuthStatus.INDETERMINATE, SecuritySource.OPERATION),
        ("weirdOp", AuthStatus.INDETERMINATE, SecuritySource.OPERATION),
        ("invalidOp", AuthStatus.INDETERMINATE, SecuritySource.OPERATION),
        ("oidcOp", AuthStatus.DECLARED_REQUIRED, SecuritySource.OPERATION),
        ("cookieOp", AuthStatus.DECLARED_REQUIRED, SecuritySource.OPERATION),
        ("basicOp", AuthStatus.DECLARED_REQUIRED, SecuritySource.OPERATION),
        ("brokenKeyOp", AuthStatus.INDETERMINATE, SecuritySource.OPERATION),
    ],
)
def test_operation_classification(spec, operation_id, status, source):
    result = _analyze(spec, operation_id)
    assert (result.status, result.source) == (status, source)


def test_empty_override_is_explained(spec):
    assert "security: []" in _analyze(spec, "publicOp").notes[0]


def test_alternatives_are_or_and_combined_are_and(spec):
    alternatives = _analyze(spec, "alternativesOp").alternatives
    assert [[usage.name for usage in alt] for alt in alternatives] == [["apiKeyHeader"], ["oauth"]]
    assert alternatives[1][0].scopes == ["read"]
    combined = _analyze(spec, "combinedOp").alternatives
    assert [[usage.name for usage in alt] for alt in combined] == [["apiKeyHeader", "apiKeyQuery"]]


def test_optional_authentication_is_flagged(spec):
    result = _analyze(spec, "optionalOp")
    assert result.optional is True
    assert result.to_dict()["optional"] is True


def test_scheme_descriptions(spec):
    describe = lambda op: _analyze(spec, op).alternatives[0][0].description  # noqa: E731
    assert describe("inheritedOp") == "HTTP Bearer (JWT)"
    assert describe("basicOp") == "HTTP Basic"
    assert describe("cookieOp") == "API key em cookie: session"
    assert describe("oidcOp") == "OpenID Connect"


def test_to_dict_is_compact(spec):
    data = _analyze(spec, "unknownOp").to_dict()
    assert data["status"] == "indeterminate"
    assert data["alternatives"] == [[{"scheme": "ghost", "scopes": [], "type": "não definido em securitySchemes"}]]
    assert data["notes"]


def test_spec_without_any_security(load_fixture):
    spec = load_fixture("incomplete.yaml")
    create = spec.find_operation("createOrder")
    result = analyze_operation_security(spec, create)
    assert (result.status, result.source) == (AuthStatus.NONE_DECLARED, SecuritySource.NOT_DECLARED)
    assert analyze_operation_security(spec, spec.find_operation("getOrder")).status is AuthStatus.INDETERMINATE


def test_swagger2_global_and_override(load_fixture):
    spec = load_fixture("petstore_v2.yaml")
    assert analyze_operation_security(spec, spec.find_operation("listPets")).source is SecuritySource.GLOBAL
    create = analyze_operation_security(spec, spec.find_operation("createPet"))
    assert create.status is AuthStatus.DECLARED_REQUIRED
    assert create.alternatives[0][0].description == "OAuth 2.0 (authorizationCode)"


def test_overview_counts(spec):
    overview = security_overview(spec)
    assert overview["operations_by_status"] == {"declared_required": 7, "none_declared": 2, "indeterminate": 4}
    assert "não foi verificado" in overview["disclaimer"]
    names = {scheme["name"] for scheme in overview["security_schemes"]}
    assert {"bearer", "oauth", "oidc"} <= names


def test_security_gaps(spec):
    gaps = {(gap.code, gap.message.split("'")[1] if "'" in gap.message else "") for gap in find_security_gaps(spec)}
    assert ("undefined_security_scheme", "ghost") in gaps
    assert ("unused_security_scheme", "unused") in gaps
    assert ("undeclared_scope", "admin") in gaps
    assert ("incomplete_security_scheme", "weird") in gaps
    assert ("incomplete_security_scheme", "brokenKey") in gaps
    assert ("invalid_security", "security") in gaps


def test_gaps_report_auth_response_consistency(spec):
    codes = {(gap.code, gap.pointer) for gap in find_security_gaps(spec)}
    assert ("auth_errors_not_documented", "/paths/~1alternatives/get") in codes
    assert ("auth_errors_not_documented", "/paths/~1inherited/get") not in codes
