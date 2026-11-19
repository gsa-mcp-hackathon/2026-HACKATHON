# Judges presentation and demonstration

Use the [20-slide deck](FEMA_Oversight_MCP_Judges_Deck.pptx). Slides 1-15 tell the story. Slides 16-20 hold the tool, evaluation, evidence, governance and GSA-template details. Speaker notes contain source links and a 90-second demonstration sequence. The matching [submission package](../SUBMISSION.md) supplies the full narrative and evaluation documentation.

[PDF preview of the same deck](FEMA_Oversight_MCP_Judges_Deck.pdf).

## Demonstrate the submitted server

1. Start the local v1.1 server using [Quickstart](../QUICKSTART.md). Confirm six tools through MCP discovery.
2. Ask where to start in LA DR-4611. Call `build_review_queue` with the exact nested JSON in [TOOLS.md](../docs/TOOLS.md). Show the returned reasons, identity and data scope.
3. Screen DR-4611 Category F. Show the returned statistics and three indicators.
4. Prepare the brief for disaster 4611, applicant `109-99109-00`, PW 1725. Inspect `indicator_check`, source records, method, timestamp and limitations. Explain the analyst's next check.

The saved [live demonstration responses](../eval/results/20261119-live-attempt/demo.json) contain three actual MCP calls captured November 19, 2026. They are not an LLM conversation or a recording of a deployed app. To create another capture with internet access:

```sh
uv run python eval/capture_demo.py --output eval/results/my-demo.json
```

Live data and response times may change. If retrieval fails during judging, clearly identify the saved November 19 response as a recorded fallback. The older hosted Databricks analyst app is a separate v1.0 implementation and is not needed to evaluate this submission.
