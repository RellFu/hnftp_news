"""
Evidence binding module

- Each claim-bearing field must link to at least one supporting evidence span
- Evidence span must include: issuing body, publication date, document type, stable source ID
- Post-generation validator checks completeness and evidence binding; triggers downgrade when binding fails
"""
