"""Golden event timeline for seed=42. Eight cross-feed scenarios over 120 sim-days (NL/DE/UK)."""

from __future__ import annotations

_seq = 0


def _evt(source: str, type_: str, sim_time: str, payload: dict) -> dict:  # type: ignore[type-arg]
    global _seq
    _seq += 1
    return {
        "eventId": f"evt_{_seq:06d}",
        "simTime": sim_time,
        "seq": _seq,
        "source": source,
        "type": type_,
        "version": "1.0",
        "payload": payload,
    }


EVENTS: list[dict] = sorted(  # type: ignore[type-arg]
    [
        # Day 0 baseline sync
        _evt("crm", "account_synced", "2026-02-01T08:00:00Z", {"accountId": "NL-0847", "healthScore": 72}),
        _evt("crm", "account_synced", "2026-02-01T08:01:00Z", {"accountId": "NL-0848", "healthScore": 80}),
        _evt("crm", "account_synced", "2026-02-01T08:02:00Z", {"accountId": "NL-0849", "healthScore": 85}),
        _evt("crm", "account_synced", "2026-02-01T08:03:00Z", {"accountId": "DE-0512", "healthScore": 78}),
        _evt("crm", "account_synced", "2026-02-01T08:04:00Z", {"accountId": "DE-0513", "healthScore": 82}),
        _evt("crm", "account_synced", "2026-02-01T08:05:00Z", {"accountId": "UK-0101", "healthScore": 80}),
        _evt("crm", "account_synced", "2026-02-01T08:06:00Z", {"accountId": "UK-0103", "healthScore": 75}),
        _evt("crm", "account_synced", "2026-02-01T08:07:00Z", {"accountId": "UK-0104", "healthScore": 83}),
        _evt("supply", "inventory_snapshot", "2026-02-01T08:10:00Z", {
            "items": [
                {"productId": "ING-1.5T",    "available": 12, "leadWeeks": 10},
                {"productId": "ING-3T",      "available": 6,  "leadWeeks": 14},
                {"productId": "SCT-7500",    "available": 4,  "leadWeeks": 16},
                {"productId": "ING-3T-REF",  "available": 2,  "leadWeeks": 4 },
                {"productId": "CONTRAST-KIT","available": 200,"leadWeeks": 1 },
            ]
        }),

        # SCENARIO 1: deal_stall — NL-0847 Erasmus MC
        # Detection window: 2026-02-10 → 2026-02-14
        # Opp stalled >30d; deal_velocity detects and requests unstick action.
        _evt("crm", "opportunity_stalled", "2026-02-10T09:00:00Z", {
            "oppId": "OPP-1001", "accountId": "NL-0847",
            "title": "Ingenia 3T MRI + Neurovascular Coil Package",
            "value": 2_400_000, "stage": "proposal",
            "daysInStage": 32, "lastActivityDate": "2026-01-09T09:00:00Z", "repId": "R-22",
        }),
        _evt("crm", "activity_logged", "2026-02-10T14:00:00Z", {
            "accountId": "NL-0847", "oppId": "OPP-1001", "type": "call",
            "subject": "Follow-up Bakker", "outcome": "no_response", "repId": "R-22",
        }),
        _evt("voice", "voice_memo_received", "2026-02-11T09:12:00Z", {
            "repId": "R-22", "accountId": "NL-0847",
            "audioUrl": "http://localhost:7002/audio/memo_0312.mp3",
            "transcript": (
                "Met Prof de Vries at Erasmus, very keen on the 3T, procurement is gatekeeping "
                "through Bakker. Naeotom visited last week and came in 200k below our list price. "
                "We should attach a coil upgrade to the open quote to defend our position."
            ),
            "capturedAt": "2026-02-11T09:12:00Z", "durationSec": 38,
        }),
        _evt("crm", "contact_sentiment_changed", "2026-02-11T16:00:00Z", {
            "accountId": "NL-0847", "contactId": "C-002", "contactName": "J. Bakker",
            "role": "Procurement Manager", "fromSentiment": "neutral", "toSentiment": "cold",
        }),

        # SCENARIO 2: competitor_rfp — NL-0847 (follows deal_stall)
        # Competitor submits formal proposal → compound scenario.
        _evt("market", "competitor_activity", "2026-02-13T10:00:00Z", {
            "accountId": "NL-0847", "competitor": "Naeotom Medical",
            "activityType": "proposal_submitted", "products": ["Naeotom Alpha.Pro 3T"],
            "confidence": "high", "source": "linkedin_intel",
        }),

        # SCENARIO 3: expansion_announcement — UK-0103 Oxford
        _evt("market", "expansion_announcement", "2026-02-20T08:00:00Z", {
            "accountId": "UK-0103", "type": "new_wing",
            "description": "Oxford University Hospitals breaks ground on new cardiac imaging centre",
            "capexBudget": 35_000_000, "imagingBudget": 6_500_000,
            "procurementTimeline": "Q3 2026", "source": "press_release",
        }),
        _evt("market", "budget_cycle_open", "2026-02-20T14:00:00Z", {
            "accountId": "UK-0103", "fiscalYear": "2026",
            "budgetCategory": "capital_equipment", "approvedAmount": 8_000_000,
            "expiresAt": "2026-04-30T23:59:59Z",
        }),

        # SCENARIO 4: inbound_capital_quote — UK-0103 Oxford
        _evt("quotes", "inbound_quote_request", "2026-02-22T09:00:00Z", {
            "accountId": "UK-0103", "fromContact": "Prof. S. Ramachandran",
            "subject": "Quote request — cardiac imaging centre 3T MRI",
            "body": (
                "Dear Philips, following approval of capital budget for our new cardiac imaging "
                "centre we would like a quote for: 1x Ingenia Elition 3T MRI with cardiac coil "
                "package and 5-year Elite service. Delivery required by October 2026. "
                "Our board has confirmed GBP 1.8M budget. Please confirm local service SLA."
            ),
            "attachmentsText": [], "urgency": "high",
        }),
        _evt("voice", "voice_memo_received", "2026-02-23T15:00:00Z", {
            "repId": "R-42", "accountId": "UK-0103",
            "audioUrl": "http://localhost:7002/audio/memo_0413.mp3",
            "transcript": (
                "Site visit Oxford today. Ramachandran is very enthusiastic about the new cardiac "
                "centre. CFO Hughes has signed off the budget. Siemens have already been in but "
                "struggling on local service coverage. We need a tight quote by end of March."
            ),
            "capturedAt": "2026-02-23T15:00:00Z", "durationSec": 42,
        }),

        # SCENARIO 5: inbound_consumable_quote — NL-0849 Radboud
        # FastFlow v1 handles this — keyword classification, zero LLM calls.
        _evt("quotes", "inbound_quote_request", "2026-03-05T11:00:00Z", {
            "accountId": "NL-0849", "fromContact": "Dr. van der Berg",
            "subject": "Consumables order — contrast media and electrode packs",
            "body": (
                "Goedendag, graag een offerte voor: 20 dozen Contrast Media Kit (50-unit) en "
                "15 dozen ECG Electrode Pack (500-unit). Levering binnen 5 werkdagen gewenst. "
                "Rekening: Radboudumc Radiologie afdeling."
            ),
            "attachmentsText": [], "urgency": "normal",
        }),

        # SCENARIO 6: rep_transition — NL-0848 Amsterdam UMC
        # Rep R-22 departs; account reassigned to R-55.
        # sales_continuity detects coverage gap and generates handoff brief.
        _evt("crm", "owner_changed", "2026-03-15T09:00:00Z", {
            "accountId": "NL-0848",
            "oldRepId": "R-22", "previousOwner": "R-22",
            "newRepId":  "R-55", "newOwner":  "R-55",
            "reason": "rep_departure",
        }),
        _evt("crm", "activity_logged", "2026-03-16T11:00:00Z", {
            "accountId": "NL-0848", "type": "note",
            "subject": "Transition note", "outcome": "pending",
            "notes": "R-22 left the company. No warm handover. OPP-1002 still open at qualification.",
            "repId": "R-55",
        }),
        _evt("crm", "opportunity_stalled", "2026-03-20T09:00:00Z", {
            "oppId": "OPP-1002", "accountId": "NL-0848",
            "title": "MRI Fleet Refresh — 2x 1.5T", "value": 1_700_000, "stage": "qualification",
            "daysInStage": 35, "lastActivityDate": "2026-02-13T09:00:00Z", "repId": "R-55",
        }),

        # SCENARIO 7: delivery_constraint — DE-0512 Charité Berlin
        _evt("quotes", "inbound_quote_request", "2026-04-01T09:00:00Z", {
            "accountId": "DE-0512", "fromContact": "H. Schmidt",
            "subject": "Urgent — 3x 3T MRI, 10-week delivery required",
            "body": (
                "Sehr geehrte Damen und Herren, wir benötigen 3 Ingenia Elition 3T-Systeme mit "
                "Lieferung innerhalb von 10 Wochen. Budget bis 30. Juni freigegeben. "
                "Bitte bestätigen Sie Verfügbarkeit und Liefertermin umgehend."
            ),
            "attachmentsText": [], "urgency": "critical",
        }),
        _evt("supply", "lead_time_extended", "2026-04-01T11:00:00Z", {
            "productId": "ING-3T", "previousLeadWeeks": 8, "newLeadWeeks": 18,
            "reason": "gradient_coil_supply_shortage", "affectedRegions": ["EMEA"],
            "updatedAt": "2026-04-01T11:00:00Z",
        }),
        _evt("crm", "opportunity_risk_flagged", "2026-04-01T16:00:00Z", {
            "oppId": "OPP-3003", "accountId": "DE-0512",
            "title": "Charité 3x 3T MRI Urgent Delivery", "value": 4_200_000,
            "riskType": "delivery_commitment",
            "riskDetail": "Customer requires 10-week delivery; factory lead time now 18 weeks",
            "repId": "R-15",
        }),
        _evt("supply", "refurb_units_available", "2026-04-02T09:00:00Z", {
            "productId": "ING-3T-REF", "unitsAvailable": 2, "condition": "certified_refurbished",
            "leadWeeks": 4, "priceDiscountPct": 44, "siteReady": ["EMEA-DACH"],
        }),
        _evt("voice", "voice_memo_received", "2026-04-02T14:00:00Z", {
            "repId": "R-15", "accountId": "DE-0512",
            "audioUrl": "http://localhost:7002/audio/memo_0521.mp3",
            "transcript": (
                "Called Schmidt at Charité this morning. He is very unhappy — budget expires June 30 "
                "and if we cannot deliver he will look at Siemens MAGNETOM who promised 10 weeks. "
                "We need to propose refurb units or get a factory commitment today."
            ),
            "capturedAt": "2026-04-02T14:00:00Z", "durationSec": 52,
        }),

        # SCENARIO 8: buyer_movement — DE-0513 Heidelberg
        # New CFO with cost-reduction mandate on contract renewal.
        _evt("crm", "contract_expiring", "2026-04-15T09:00:00Z", {
            "accountId": "DE-0513", "contractId": "SVC-2022-0088",
            "productId": "SVC-ELITE", "annualValue": 95_000,
            "totalRemainingValue": 1_900_000, "expiresAt": "2026-06-30T23:59:59Z",
            "daysUntilExpiry": 76, "repId": "R-15",
        }),
        _evt("market", "executive_change", "2026-04-16T11:00:00Z", {
            "accountId": "DE-0513", "contactId": "C-008", "role": "CFO",
            "previousName": "M. Brandt", "newName": "Dr. A. Fischer",
            "effectiveDate": "2026-04-01", "mandate": "cost_reduction_12pct",
            "source": "linkedin",
        }),
        _evt("voice", "voice_memo_received", "2026-04-18T10:00:00Z", {
            "repId": "R-15", "accountId": "DE-0513",
            "audioUrl": "http://localhost:7002/audio/memo_0614.mp3",
            "transcript": (
                "Introductory call with Fischer, the new CFO at Heidelberg. She has a 12% cost-cut "
                "mandate and questioned the service contract renewal. She wants ROI justification "
                "and implied competitive tender is on the table. Weber in Radiology is supportive "
                "but Fischer controls the budget. Need to move fast."
            ),
            "capturedAt": "2026-04-18T10:00:00Z", "durationSec": 58,
        }),
        _evt("market", "competitor_activity", "2026-04-20T10:00:00Z", {
            "accountId": "DE-0513", "competitor": "Siemens Healthineers",
            "activityType": "cold_outreach", "channel": "email",
            "notes": "Siemens sent unsolicited service benchmarking to Fischer on April 19.",
            "confidence": "medium",
        }),

        # SCENARIO: data_quality (issues detected across the portfolio)
        # All four are pure CRM events — the agent detects problems via rules, zero LLM.

        # DQ-1: Possible duplicate account — similar name, different ID (Day 5)
        _evt("crm", "account_synced", "2026-02-06T08:00:00Z", {
            "accountId": "NL-0847B",
            "name": "Erasmus Medical Center Rotterdam",  # ~80% similar to NL-0847
            "healthScore": 70,
            "note": "Migrated from legacy CRM — verify against NL-0847",
        }),

        # DQ-2: Stale contact on UK-0101 — last activity 210 days ago (Day 10)
        _evt("crm", "contact_updated", "2026-02-11T09:00:00Z", {
            "accountId": "UK-0101",
            "contactId": "C-011",
            "name": "Dr. C. Patel",
            "role": "Radiology Chief",
            "email": "c.patel@mft.nhs.uk",
            "lastActivityDate": "2025-07-16T00:00:00Z",  # 210 days before Feb 11 2026
            "emailBounced": False,
        }),

        # DQ-3: Mislabelled stage — closed_won with no close date and zero value (Day 15)
        _evt("crm", "opportunity_created", "2026-02-16T10:00:00Z", {
            "oppId": "OPP-DQ-001",
            "accountId": "UK-0103",
            "title": "CT Scanner Refresh",
            "value": 0,
            "stage": "closed_won",
            "closeDate": None,
            "probability": 1.0,
            "products": ["SCT-7500"],
            "repId": "R-42",
        }),

        # DQ-4: Orphaned opportunity — rep R-22 departed (Day 43) but this opp still assigned (Day 47)
        _evt("crm", "opportunity_stalled", "2026-03-19T09:00:00Z", {
            "oppId": "OPP-DQ-002",
            "accountId": "NL-0848",
            "title": "Ultrasound Suite Upgrade",
            "value": 450_000,
            "stage": "proposal",
            "daysInStage": 47,
            "repId": "R-22",  # R-22 departed on 2026-03-15
            "lastActivityDate": "2026-01-31T09:00:00Z",
        }),

        # inbound_rfq — UK-0103 Oxford (NHS SBS Framework formal tender, follows capital quote)
        _evt("quotes", "inbound_rfq", "2026-03-01T09:00:00Z", {
            "accountId": "UK-0103", "fromContact": "NHS SBS Procurement",
            "subject": "NHS SBS Framework LOT-2 ITT — MRI Systems UK-0103-2026",
            "body": (
                "Oxford University Hospitals NHS Foundation Trust is inviting tenders under "
                "the NHS Shared Business Services Imaging Equipment Framework Lot 2. "
                "Scope: 1x Ingenia Elition 3T MRI system with 5-year Elite service coverage. "
                "Submission deadline: 15 March 2026 17:00 GMT. Mandatory: ISO 13485 certification, "
                "UK clinical support team SLA, and equipment performance guarantee."
            ),
            "attachmentsText": ["NHS_SBS_LOT2_ITT_Spec_v3.pdf"],
            "urgency": "high",
        }),
    ],
    key=lambda e: e["simTime"],
)
