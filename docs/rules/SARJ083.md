# SARJ083 `no-implicit-attribute-access` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_implicit_attribute_access.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

The anti-pattern:
    price = foo.get("price")
    user_id = event["user_id"]

Accessing dictionaries with hardcoded string literals implies the object has a known schema.
This should be parsed declaratively with Pydantic instead of plucked manually.

Define a Pydantic model and parse the payload at the boundary instead:
    class Payload(BaseModel):
        price: int
        user_id: str

    data = Payload.model_validate(foo)
    price = data.price
