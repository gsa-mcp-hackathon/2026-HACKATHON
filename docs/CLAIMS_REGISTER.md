# Claims register

Current submitted server: **1.1.0**, MCP display name **FEMA Evidence & Oversight Graph**, submission title **FEMA Oversight MCP**. These identify the same implementation. Canonical source: root `src/fema_oversight/`.

Current full evaluation: [`20261119T134625Z`](../eval/results/20261119-live-attempt/summary.json), November 19, 2026. Source SHA-256 `6dee75f765962a954ca75ca7cb5884d5f198f48eac87d3408fa7cff78386dd98`. The source code matches the November 18 v1.1 fingerprint. Packaging, documentation and harness changes are covered separately in the release manifest.

| Claim | Value and unit | Exact evidence | Deck / package |
| --- | --- | --- | --- |
| Unit and contract tests | 63 passed, no failures | [pytest XML](../eval/results/20261119-local/pytest.xml) | Slide 11 / Section 11 |
| Offline evaluation | 33/33 checks | [offline summary](../eval/results/20261119-local/summary.json), passed and total | Section 11, evaluation guide |
| Complete evaluation | 37/37 checks | [live summary](../eval/results/20261119-live-attempt/summary.json), passed and total | Slides 11, 17 / Section 11, Appendix B |
| Suites | 3 controls + 19 errors + 5 contracts + 6 stability + 4 live = 37 | summary.suites | Slide 17 / Appendix B |
| Presentation groupings | Calculation agreement 11, tool contracts 5, errors/workflows 21 | Controls 3 + stability 6 + two live screens = 11; contract 5; errors 19 + two workflow assertions = 21 | Slides 11, 17 / Section 11 |
| MCP inventory | 6 tools, 2 resources, 1 prompt | [contract tests](../tests/test_contract.py), `test_exact_tool_set`, `test_resources_and_prompt` | Slide 16 / Section 6 |
| Fixture controls | Cost share 238 rows; repeated titles 74 groups; category costs 3 rows | live summary, suites.controls; [fixture manifest](../eval/fixtures/MANIFEST.json) | Slide 17 / Appendix B |
| LA DR-4611 queue scope | 3,648 retrieved rows; cap not reached | suites.live, queue check; [actual MCP response](../eval/results/20261119-live-attempt/demo.json), first call data_scope | Slides 2, 6-7, 18 / Section 7 |
| Queue totals | 55 category-outlier rows; 134 repeated-title groups; 1,510 cost-share rows | queue check indicator_totals, actual queue response | Slides 7, 18 / Section 7 |
| Queue first five | PWs 966, 2106, 732, 2105, 1900, each with three distinct indicator types | live queue check top; demo first call queue | Slides 7, 18 / Section 7 |
| Queue ranking | Distinct indicator count, then project amount, then PW | [review.py](../src/fema_oversight/tools/review.py), priority | Slide 7 / Section 7 |
| LA DR-4611 Category F | 115 numeric baseline records; PWs 1725, 1679, 5757; sigma 7.73, 4.75, 3.29 | live category check; demo second call category_stats and indicators | Slides 6, 8, 18 / Section 7 |
| PW 1725 | Applicant 109-99109-00; Houma Power Plant; amount $149,603,170.72; federal and total obligated each $134,642,853.65 | demo third call source_records | Slide 8 / Section 7 |
| Brief re-check | Default threshold 3.0; measured sigma 7.73; baseline 115 | live brief check and demo third call indicator_check | Slides 8, 18 / Section 7 |
| NC DR-4827 repeats | 86 groups over 3,107 rows; 2 same_wording | live repeated-group check | Slide 18 / Appendix C |
| Snapshot timing | Per-tool medians 7.2-100.8 ms, 10 calls per tool | live summary.latency | Slides 11, 17 / Section 11 |
| Live timing | Category 0.44 s; repeats 0.26 s; brief 1.95 s; queue 13.95 s | live summary.latency.live_seconds | Slides 11, 17 / Section 11 |
| Demonstration capture | 3/3 actual live MCP calls, no model | demo.json, is_error=false on all calls; timestamps inside responses | Section 7 and presentation guide |
| GSA template relationship | Adapted structure and FastMCP pattern; pinned upstream f39249f17683 | [file map](GSA_TEMPLATE_ALIGNMENT.md) | Slide 20 / Appendix E |

Queue indicator totals use different units and can overlap. The repeated-title grouping counts rows without deduplicating upstream duplicates. No total in this table is an amount of suspected fraud, an improper-payment finding, a calibrated risk score, or measured reviewer agreement.

Two live screens are compared with independent direct queries. The brief and queue checks are workflow assertions, not independent validation of every field. The 11/5/21 groupings are presentation categories, not detection accuracy or evidence-completeness scores. Latency reflects these calls on this machine and public endpoint, not an SLA.

Historical v1.0 measurements and the November 18 v1.1 report retain their original dates and scope. Only the November 19 evidence above supports current pass counts and timings. A proposed pilot remains proposed. No production deployment, model-selection re-evaluation, measured savings, agency endorsement or certified policy compliance is claimed.
