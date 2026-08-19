from pathlib import Path


SCHEMAS_DIR = Path(__file__).resolve().parent
RULE_CATALOG = SCHEMAS_DIR / "rule-catalog.v1.json"
RULE_CATALOG_SCHEMA = SCHEMAS_DIR / "rule-catalog.v1.schema.json"
SLACK_AUTOMATIONS_SCHEMA = SCHEMAS_DIR / "slack-automations.v1.schema.json"
