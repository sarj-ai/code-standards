from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

from sarj_python_lint.rules.prefer_match_type_dispatch import PreferMatchTypeDispatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


SRC_PATH = "python/app/models/call_detail.py"


def _check(source: str, path: str = SRC_PATH) -> list[Diagnostic]:
    return PreferMatchTypeDispatch().check(Path(path), textwrap.dedent(source))


# --------------------------------------------------------------------------- #
# Core detection: Hideous parser helper / raise-in-try idiom                 #
# --------------------------------------------------------------------------- #


_HIDEOUS_PARSER_IDIOM = """
def _parse_transferred_at(data: object) -> datetime | None | Unset:
    if data is None:
        return data
    if isinstance(data, Unset):
        return data
    try:
        if not isinstance(data, str):
            raise TypeError()
        transferred_at_type_0 = datetime.fromisoformat(data)
        return transferred_at_type_0
    except (TypeError, ValueError, AttributeError, KeyError):
        pass
    return cast(datetime | None | Unset, data)
"""


def test_flags_hideous_parser_helper():
    diags = _check(_HIDEOUS_PARSER_IDIOM)
    assert len(diags) >= 1
    codes = {d.code for d in diags}
    assert "SARJ080" in codes


def test_flags_control_flow_raise_inside_try():
    source = """
    def parse_item(val):
        try:
            if not isinstance(val, int):
                raise ValueError()
            return val * 2
        except ValueError:
            return 0
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ080"
    assert "Control-flow raise in try block" in diags[0].message
    assert diags[0].line == 5


def test_flags_sequential_sentinel_guards():
    source = """
    def _parse_field(val: object):
        if val is None:
            return val
        if isinstance(val, Unset):
            return val
        if isinstance(val, int):
            return str(val)
        return None
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ080"
    assert "Sequential sentinel/type guards" in diags[0].message


def test_flags_qualified_attribute_exceptions():
    source = """
    def parse_mod_exc(val):
        try:
            if not isinstance(val, str):
                raise my_module.CustomTypeError()
            return val
        except my_module.CustomTypeError:
            return None
    """
    diags = _check(source)
    assert len(diags) == 1
    assert "raise CustomTypeError()" in diags[0].message


def test_flags_raised_exception_attribute_no_call():
    source = """
    def parse_item(val):
        try:
            if not isinstance(val, int):
                raise builtins.ValueError
            return val
        except builtins.ValueError:
            return None
    """
    diags = _check(source)
    assert len(diags) == 1


def test_flags_tuple_exception_handlers():
    source = """
    def parse_item(val):
        try:
            if not isinstance(val, int):
                raise TypeError()
            return val
        except (ValueError, builtins.TypeError):
            return None
    """
    diags = _check(source)
    assert len(diags) == 1


def test_try_star():
    source = """
    def parse_item(val):
        try:
            if not isinstance(val, int):
                raise ValueError()
            return val
        except* ValueError:
            return None
    """
    diags = _check(source)
    assert len(diags) == 1


def test_nested_try_blocks():
    source = """
    def foo(val):
        try:
            try:
                if not isinstance(val, int):
                    raise ValueError()
                return val
            except ValueError:
                return None
        except TypeError:
            return 0
    """
    diags = _check(source)
    assert len(diags) == 1


def test_skips_inner_function_try_block_from_outer_scope():
    source = """
    def outer():
        try:
            def inner():
                raise ValueError()
            inner()
        except ValueError:
            pass
    """
    assert _check(source) == []


def test_skips_legitimate_raise_not_caught_by_local_try():
    source = """
    def validate(val):
        try:
            if val < 0:
                raise ValueError("Negative value")
            process(val)
        except TypeError:
            pass
    """
    assert _check(source) == []


def test_skips_lowercase_exception_variable_caught_by_its_class():
    source = """
    def validate(val):
        try:
            if val < 0:
                err = ValueError("Negative value")
                raise err
            return process(val)
        except ValueError:
            return None
    """
    assert _check(source) == []


def test_skips_match_case_idiom():
    source = """
    def parse_clean(data: object):
        match data:
            case None | Unset():
                return data
            case str():
                try:
                    return datetime.fromisoformat(data)
                except ValueError:
                    pass
        return cast(data)
    """
    assert _check(source) == []


def test_skips_generated_source():
    source = """
    # Automatically generated by openapi generator. DO NOT EDIT!
    def _parse_transferred_at(data: object):
        if data is None:
            return data
        if isinstance(data, Unset):
            return data
        try:
            if not isinstance(data, str):
                raise TypeError()
            return datetime.fromisoformat(data)
        except TypeError:
            pass
        return data
    """
    assert _check(source) == []


# --------------------------------------------------------------------------- #
# Control-flow-raise arm: measured false-positive classes, deliberately not   #
# flagged. Each of these was reported before the 24,644-file audit.           #
# --------------------------------------------------------------------------- #


def test_skips_handler_that_re_raises_unchanged():
    """920/1,364 of this arm: the handler propagates, so nothing jumps locally."""
    source = """
    def update_team_callbacks(request):
        try:
            if not request.team_id:
                raise ProxyException("team_id required")
            return apply(request)
        except ProxyException as e:
            log.exception("callback update failed")
            raise e
    """
    assert _check(source) == []


def test_skips_handler_that_re_raises_a_wrapped_exception():
    source = """
    def load(payload):
        try:
            if not isinstance(payload, dict):
                raise ValueError("bad payload")
            return payload["body"]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    """
    assert _check(source) == []


def test_skips_handler_where_both_branches_raise():
    source = """
    def load(payload):
        try:
            if not isinstance(payload, dict):
                raise ValueError("bad payload")
            return payload["body"]
        except ValueError as exc:
            if strict:
                raise
            else:
                raise HTTPException(status_code=400) from exc
    """
    assert _check(source) == []


def test_flags_handler_that_only_sometimes_re_raises():
    """Upper bound on the re-raise guard: a conditional re-raise still reports.

    The guard is for handlers that *always* propagate. A handler with a normal
    exit path still consumes the exception on that path, which is the dispatch
    this rule is about.
    """
    source = """
    def load(payload):
        try:
            if not isinstance(payload, dict):
                raise ValueError("bad payload")
            return payload["body"]
        except ValueError:
            if strict:
                raise
            return {}
    """
    diags = _check(source)
    assert len(diags) == 1


def test_skips_generic_exception_fault_barrier():
    """647/1,364 of this arm matched only via `except Exception`, never by name."""
    source = """
    def create_team(request):
        try:
            if not request.team_id:
                raise ProxyException("team_id required")
            return build(request)
        except Exception as exc:
            log.exception("unhandled")
            return error_response(exc)
    """
    assert _check(source) == []


def test_skips_exact_handler_shadowed_by_an_earlier_generic_handler():
    source = """
    def create_team(request):
        try:
            if not request.team_id:
                raise ProxyException("team_id required")
            return build(request)
        except Exception:
            return error_response()
        except ProxyException:
            return invalid_team_response()
    """
    assert _check(source) == []


def test_skips_bare_except_fault_barrier():
    source = """
    def parse_bare(val):
        try:
            if not isinstance(val, str):
                raise TypeError()
            return val
        except:
            return None
    """
    assert _check(source) == []


def test_skips_base_exception_only_type_under_except_exception():
    """`except Exception` does not catch `SystemExit`; reporting it was unsound."""
    source = """
    def shutdown(code):
        try:
            if code:
                raise SystemExit(code)
            return run()
        except Exception:
            return None
    """
    assert _check(source) == []


def test_flags_exception_raised_and_caught_by_its_own_name():
    """Upper bound on the explicit-name guard: `raise Exception` / `except Exception`."""
    source = """
    def parse_item(val):
        try:
            if not isinstance(val, int):
                raise Exception("not an int")
            return val
        except Exception:
            return 0
    """
    diags = _check(source)
    assert len(diags) == 1


def test_skips_raise_inside_a_long_try_body():
    body = "\n".join(f"            step_{i}()" for i in range(30))
    source = f"""
    def endpoint(request):
        try:
            if not request.user:
                raise ValueError("no user")
{body}
            return ok()
        except ValueError:
            return error()
    """
    assert _check(source) == []


def test_flags_raise_in_a_try_body_at_the_span_limit():
    """Upper bound on the span guard: exactly 20 lines still reports."""
    body = "\n".join(f"            step_{i}()" for i in range(17))
    source = f"""
    def endpoint(request):
        try:
            if not request.user:
                raise ValueError("no user")
{body}
            return ok()
        except ValueError:
            return error()
    """
    diags = _check(source)
    assert len(diags) == 1


def test_skips_try_body_that_is_only_a_raise():
    """132/1,364: scaffolding that raises in order to obtain a live exception.

    `ExceptionInfo()` reads `sys.exc_info()`, so there is no other way to build
    one. There is no dispatch here to rewrite as match/case.
    """
    source = """
    def build_einfo():
        try:
            raise Reject(requeue=True)
        except Reject:
            einfo = ExceptionInfo(internal=True)
        return einfo
    """
    assert _check(source, path="python/app/support/einfo.py") == []


def test_skips_control_flow_raise_in_a_test_file():
    """In a test the raise *is* the condition under test, not a dispatch."""
    source = """
    def test_does_not_execute_if_transaction_rolled_back(self):
        try:
            with transaction.atomic():
                self.do(1)
                raise ForcedError()
        except ForcedError:
            pass
        self.assertDone([])
    """
    assert _check(source, path="python/tests/test_transaction_hooks.py") == []


def test_sequential_guards_still_report_in_a_test_file():
    """The test exemption is scoped to the control-flow-raise arm only.

    A field deserializer defined in a test-support module is still a real
    finding; one of the six corpus survivors is exactly that.
    """
    source = """
    class TagField(Field):
        def to_python(self, value):
            if isinstance(value, Tag):
                return value
            if value is None:
                return value
            return Tag(int(value))
    """
    diags = _check(source, path="python/tests/postgres/models.py")
    assert len(diags) == 1
    assert "Sequential sentinel/type guards" in diags[0].message


# --------------------------------------------------------------------------- #
# Surviving true positives, transcribed from the OSS corpus. These pin the    #
# control-flow-raise arm's population against a guard quietly widening.       #
# --------------------------------------------------------------------------- #


def test_flags_django_was_modified_since_shape():
    """django/django/views/static.py:116 and :119."""
    source = """
    def was_modified_since(header=None, mtime=0):
        try:
            if header is None:
                raise ValueError
            header_mtime = parse_http_date(header)
            if int(mtime) > header_mtime:
                raise ValueError
        except (ValueError, OverflowError):
            return True
        return False
    """
    diags = _check(source)
    assert len(diags) == 2
    assert [d.line for d in diags] == [5, 8]


def test_flags_django_normalize_together_shape():
    """django/django/db/models/options.py:74."""
    source = """
    def normalize_together(option_together):
        try:
            if not option_together:
                return ()
            if not isinstance(option_together, (tuple, list)):
                raise TypeError
            first_element = option_together[0]
            if not isinstance(first_element, (tuple, list)):
                option_together = (option_together,)
            return tuple(tuple(ot) for ot in option_together)
        except TypeError:
            return option_together
    """
    diags = _check(source)
    assert len(diags) == 1
    assert "raise TypeError()" in diags[0].message


# --------------------------------------------------------------------------- #
# Sequential-guard arm: measured false-positive classes.                      #
# --------------------------------------------------------------------------- #


def test_skips_guards_returning_a_different_value():
    """261/271 of this arm returned something other than the guarded variable.

    These are ordinary early returns, not the sentinel-passthrough idiom the
    module docstring describes.
    """
    source = """
    def most_recent_job(job_type, session):
        if job_type == "TriggererJob":
            return None
        if job_type is None:
            return None
        return session.query(Job).first()
    """
    assert _check(source) == []


def test_skips_guards_with_no_type_check_in_the_chain():
    """74/271 contained no type check at all — enum/string equality early returns."""
    source = """
    def resolve_kind(kind):
        if kind == "PENDING":
            return kind
        if kind == "ACTIVE":
            return kind
        return normalize(kind)
    """
    assert _check(source) == []


def test_skips_bare_name_sentinel_comparator():
    """`case TICKET_NOT_FOUND:` is a capture pattern — it matches every value.

    Suggesting match/case here would silently break the code, so this shape is
    deliberately never reported. 5/271 of this arm were this.
    """
    source = """
    def summarize(ticket_data, other):
        if ticket_data is TICKET_NOT_FOUND:
            return ticket_data
        if ticket_data is UNSET:
            return ticket_data
        return render(ticket_data)
    """
    assert _check(source) == []


def test_skips_single_passthrough_guard():
    source = """
    def to_python(value):
        if value is None:
            return value
        return parse(value)
    """
    assert _check(source) == []


def test_flags_django_to_python_shape():
    """django/django/db/models/fields/__init__.py:1639 — a surviving true positive."""
    source = """
    def to_python(self, value):
        if value is None:
            return value
        if isinstance(value, datetime.datetime):
            return value
        return self.parse(value)
    """
    diags = _check(source)
    assert len(diags) == 1
    assert "2 checks on 'value'" in diags[0].message


def test_flags_issubclass_and_is_not_none_passthrough_guards():
    source = """
    def normalize(value):
        if issubclass(value, BaseModel):
            return value
        if value is not None:
            return value
        return Missing
    """
    diags = _check(source)
    assert len(diags) == 1
    assert "2 checks on 'value'" in diags[0].message


def test_flags_passthrough_guards_after_a_docstring():
    source = '''
    def deserialize(o):
        """Deserialize an object."""
        if o is None:
            return o
        if isinstance(o, _primitives):
            return o
        return _deserialize(o)
    '''
    diags = _check(source)
    assert len(diags) == 1


def test_skips_passthrough_guards_on_different_variables():
    source = """
    def combine(left, right):
        if left is None:
            return left
        if right is None:
            return right
        return left + right
    """
    assert _check(source) == []
